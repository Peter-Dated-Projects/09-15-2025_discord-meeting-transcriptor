"""
GPU Resource Manager.

This service manages GPU resource access with priority-based scheduling.
It provides a centralized lock system that allows different job types to
acquire exclusive GPU access with intelligent priority handling:

1. Priority scheduling:
   - Chatbot requests have highest priority (always processed immediately)
   - When no chatbot requests exist, uses round-robin between transcription, embedding, and summarization
   - 35% transcription, 30% embedding, 25% summarization split
   - Max 2 consecutive transcription operations before forcing switch
   - Max 1 consecutive embedding operation before forcing switch
   - Max 1 consecutive summarization operation before switching

2. GPU resource locking:
   - Only one operation can hold GPU lock at a time
   - Async lock/unlock pattern
   - Automatic priority-based queue management

Usage:
    # In any job that needs GPU:
    async with services.gpu_resource_manager.acquire_lock(job_type="transcription"):
        # GPU work here (Whisper, LLM, etc.)
        result = await whisper_client.inference(...)
"""

from __future__ import annotations

import asyncio
import enum
import random
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from source.context import Context

from source.services.gpu_resource_manager.lock import GPUResourceLock
from source.services.manager import Manager


class GPUJobType(enum.Enum):
    """Type of GPU operation."""

    TRANSCRIPTION = "transcription"
    TEXT_EMBEDDING = "text_embedding"
    SUMMARIZATION = "summarization"
    CHATBOT = "chatbot"


class GPUResourceManager(Manager):
    """
    Manager for GPU resources with priority-based scheduling.

    This manager provides a centralized GPU lock that can be acquired by
    different job types with intelligent priority and round-robin scheduling.
    """

    def __init__(
        self,
        context: Context,
    ):
        """
        Initialize the GPU resource manager.

        Args:
            context: Application context
        """
        super().__init__(context)

        # GPU resource lock
        self._gpu_lock = GPUResourceLock()

        # Priority queues for pending lock requests
        self._transcription_queue: asyncio.Queue[asyncio.Event] = asyncio.Queue()
        self._text_embedding_queue: asyncio.Queue[asyncio.Event] = asyncio.Queue()
        self._summarization_queue: asyncio.Queue[asyncio.Event] = asyncio.Queue()
        self._chatbot_queue: asyncio.Queue[asyncio.Event] = asyncio.Queue()

        # Scheduler state
        self._consecutive_transcription_count = 0
        self._consecutive_text_embedding_count = 0
        self._consecutive_summarization_count = 0
        self._last_job_type: GPUJobType | None = None
        self._scheduler_running = False
        self._scheduler_task: asyncio.Task | None = None

        # Scheduling parameters
        self.MAX_CONSECUTIVE_TRANSCRIPTION = 2
        self.MAX_CONSECUTIVE_TEXT_EMBEDDING = 1
        self.MAX_CONSECUTIVE_SUMMARIZATION = 1
        self.TRANSCRIPTION_PROBABILITY = 0.35  # 35% chance
        self.TEXT_EMBEDDING_PROBABILITY = 0.30  # 30% chance
        self.SUMMARIZATION_PROBABILITY = 0.25  # 25% chance
        # Remaining 10% for fallback logic

        # Statistics
        self._total_transcription_locks = 0
        self._total_text_embedding_locks = 0
        self._total_summarization_locks = 0
        self._total_chatbot_locks = 0

    # -------------------------------------------------------------- #
    # Manager Lifecycle
    # -------------------------------------------------------------- #

    async def on_start(self, services) -> None:
        """Actions to perform on manager start."""
        await super().on_start(services)
        await self._start_scheduler()
        if self.services:
            await self.services.logging_service.info("GPU Resource Manager started")

    async def on_close(self) -> None:
        """Actions to perform on manager shutdown."""
        await self._stop_scheduler()
        if self.services:
            await self.services.logging_service.info("GPU Resource Manager stopped")

    # -------------------------------------------------------------- #
    # GPU Lock Acquisition
    # -------------------------------------------------------------- #

    def acquire_lock(
        self, job_type: str | GPUJobType, job_id: str = "unknown", metadata: dict = None
    ):
        """
        Acquire GPU lock with priority-based scheduling.

        This is an async context manager:
            async with gpu_manager.acquire_lock("transcription"):
                # Do GPU work

        Args:
            job_type: Type of job requesting GPU ("transcription", "text_embedding", "summarization", "chatbot")
            job_id: Optional job identifier for logging
            metadata: Optional metadata about the job

        Returns:
            Async context manager that handles lock acquisition and release
        """
        # Convert string to enum if needed
        if isinstance(job_type, str):
            try:
                job_type = GPUJobType(job_type.lower())
            except ValueError:
                raise ValueError(
                    f"Invalid job_type: {job_type}. Must be one of: transcription, text_embedding, summarization, chatbot"
                )

        return _GPULockContext(self, job_type, job_id, metadata or {})

    async def _request_lock(self, job_type: GPUJobType, job_id: str, metadata: dict) -> None:
        """
        Request GPU lock and wait until it's granted.

        Args:
            job_type: Type of job requesting GPU
            job_id: Job identifier
            metadata: Job metadata
        """
        # Create an event that will be signaled when this request can proceed
        ready_event = asyncio.Event()

        # Add to appropriate priority queue
        if job_type == GPUJobType.CHATBOT:
            await self._chatbot_queue.put(ready_event)
        elif job_type == GPUJobType.TRANSCRIPTION:
            await self._transcription_queue.put(ready_event)
        elif job_type == GPUJobType.TEXT_EMBEDDING:
            await self._text_embedding_queue.put(ready_event)
        elif job_type == GPUJobType.SUMMARIZATION:
            await self._summarization_queue.put(ready_event)

        if self.services:
            await self.services.logging_service.info(
                f"GPU lock requested by {job_type.value} job {job_id}"
            )

        # Wait for the scheduler to grant access
        await ready_event.wait()

        # Now acquire the actual lock (this is just bookkeeping, not blocking)
        self._gpu_lock.acquire(job_id=job_id, job_type=job_type.value, metadata=metadata)

        # Update statistics
        if job_type == GPUJobType.TRANSCRIPTION:
            self._total_transcription_locks += 1
        elif job_type == GPUJobType.TEXT_EMBEDDING:
            self._total_text_embedding_locks += 1
        elif job_type == GPUJobType.SUMMARIZATION:
            self._total_summarization_locks += 1
        elif job_type == GPUJobType.CHATBOT:
            self._total_chatbot_locks += 1

        if self.services:
            await self.services.logging_service.info(
                f"GPU lock acquired by {job_type.value} job {job_id}"
            )

    async def _release_lock(self, job_type: GPUJobType, job_id: str) -> None:
        """
        Release GPU lock.

        Args:
            job_type: Type of job releasing GPU
            job_id: Job identifier
        """
        self._gpu_lock.release()

        # Update consecutive counts
        self._update_stats(job_type)

        if self.services:
            await self.services.logging_service.info(
                f"GPU lock released by {job_type.value} job {job_id}"
            )

    def _update_stats(self, job_type: GPUJobType) -> None:
        """Update scheduler statistics after processing a job."""
        if job_type == GPUJobType.TRANSCRIPTION:
            if self._last_job_type == GPUJobType.TRANSCRIPTION:
                self._consecutive_transcription_count += 1
            else:
                self._consecutive_transcription_count = 1
            self._consecutive_text_embedding_count = 0
            self._consecutive_summarization_count = 0

        elif job_type == GPUJobType.TEXT_EMBEDDING:
            if self._last_job_type == GPUJobType.TEXT_EMBEDDING:
                self._consecutive_text_embedding_count += 1
            else:
                self._consecutive_text_embedding_count = 1
            self._consecutive_transcription_count = 0
            self._consecutive_summarization_count = 0

        elif job_type == GPUJobType.SUMMARIZATION:
            if self._last_job_type == GPUJobType.SUMMARIZATION:
                self._consecutive_summarization_count += 1
            else:
                self._consecutive_summarization_count = 1
            self._consecutive_transcription_count = 0
            self._consecutive_text_embedding_count = 0

        elif job_type == GPUJobType.CHATBOT:
            # Chatbot doesn't affect consecutive counts
            pass

        self._last_job_type = job_type

    # -------------------------------------------------------------- #
    # Priority Scheduler
    # -------------------------------------------------------------- #

    async def _start_scheduler(self) -> None:
        """Start the GPU priority scheduler."""
        if self._scheduler_running:
            return

        self._scheduler_running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())

    async def _stop_scheduler(self) -> None:
        """Stop the GPU scheduler."""
        if not self._scheduler_running:
            return

        import contextlib

        self._scheduler_running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._scheduler_task

    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop that grants GPU access based on priority.

        Priority order:
        1. Chatbot requests (always highest priority)
        2. Round-robin between transcription, text embedding, and summarization
           - 35% probability for transcription
           - 30% probability for text embedding
           - 25% probability for summarization
           - Max 2 consecutive transcription operations
           - Max 1 consecutive text embedding operation
           - Max 1 consecutive summarization operation
        """
        while self._scheduler_running:
            try:
                # Wait a bit for the current lock holder to finish
                await asyncio.sleep(0.5)

                # Only schedule next if GPU is not currently locked
                if self._gpu_lock.is_locked():
                    continue

                # Check for chatbot requests first (highest priority)
                if not self._chatbot_queue.empty():
                    ready_event = await self._chatbot_queue.get()
                    ready_event.set()
                    continue

                # If no chatbot requests, use round-robin for transcription/embedding/summarization
                next_job_type = self._select_next_job_type()

                if next_job_type == GPUJobType.TRANSCRIPTION:
                    if not self._transcription_queue.empty():
                        ready_event = await self._transcription_queue.get()
                        ready_event.set()
                    elif not self._text_embedding_queue.empty():
                        # Fall back to text embedding if no transcription requests
                        ready_event = await self._text_embedding_queue.get()
                        ready_event.set()
                    elif not self._summarization_queue.empty():
                        # Fall back to summarization if no transcription or embedding requests
                        ready_event = await self._summarization_queue.get()
                        ready_event.set()

                elif next_job_type == GPUJobType.TEXT_EMBEDDING:
                    if not self._text_embedding_queue.empty():
                        ready_event = await self._text_embedding_queue.get()
                        ready_event.set()
                    elif not self._transcription_queue.empty():
                        # Fall back to transcription if no embedding requests
                        ready_event = await self._transcription_queue.get()
                        ready_event.set()
                    elif not self._summarization_queue.empty():
                        # Fall back to summarization if no embedding or transcription requests
                        ready_event = await self._summarization_queue.get()
                        ready_event.set()

                elif next_job_type == GPUJobType.SUMMARIZATION:
                    if not self._summarization_queue.empty():
                        ready_event = await self._summarization_queue.get()
                        ready_event.set()
                    elif not self._text_embedding_queue.empty():
                        # Fall back to text embedding if no summarization requests
                        ready_event = await self._text_embedding_queue.get()
                        ready_event.set()
                    elif not self._transcription_queue.empty():
                        # Fall back to transcription if no summarization or embedding requests
                        ready_event = await self._transcription_queue.get()
                        ready_event.set()

            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.services:
                    await self.services.logging_service.error(
                        f"Error in GPU scheduler loop: {type(e).__name__}: {str(e)}"
                    )
                await asyncio.sleep(1.0)

    def _select_next_job_type(self) -> GPUJobType | None:
        """
        Select the next job type to process based on round-robin rules.

        Rules:
        - If we've done MAX_CONSECUTIVE_TRANSCRIPTION in a row, force switch to embedding or summarization
        - If we've done MAX_CONSECUTIVE_TEXT_EMBEDDING in a row, force switch to transcription or summarization
        - If we've done MAX_CONSECUTIVE_SUMMARIZATION in a row, force switch to transcription or embedding
        - Otherwise, use probability-based selection (35% transcription, 30% embedding, 25% summarization)
        """
        # Check if we need to force a switch due to consecutive limits
        if (
            self._last_job_type == GPUJobType.TRANSCRIPTION
            and self._consecutive_transcription_count >= self.MAX_CONSECUTIVE_TRANSCRIPTION
        ):
            # Switch away from transcription - prefer embedding over summarization
            if random.random() < 0.55:  # 30/(30+25) ≈ 0.545
                return GPUJobType.TEXT_EMBEDDING
            else:
                return GPUJobType.SUMMARIZATION

        if (
            self._last_job_type == GPUJobType.TEXT_EMBEDDING
            and self._consecutive_text_embedding_count >= self.MAX_CONSECUTIVE_TEXT_EMBEDDING
        ):
            # Switch away from embedding - prefer transcription over summarization
            if random.random() < 0.58:  # 35/(35+25) ≈ 0.583
                return GPUJobType.TRANSCRIPTION
            else:
                return GPUJobType.SUMMARIZATION

        if (
            self._last_job_type == GPUJobType.SUMMARIZATION
            and self._consecutive_summarization_count >= self.MAX_CONSECUTIVE_SUMMARIZATION
        ):
            # Switch away from summarization - prefer transcription over embedding
            if random.random() < 0.54:  # 35/(35+30) ≈ 0.538
                return GPUJobType.TRANSCRIPTION
            else:
                return GPUJobType.TEXT_EMBEDDING

        # Use probability-based selection
        # Total probability allocated: 35% + 30% + 25% = 90%, leaving 10% for fallback
        rand_val = random.random()
        
        if rand_val < self.TRANSCRIPTION_PROBABILITY:
            return GPUJobType.TRANSCRIPTION
        elif rand_val < self.TRANSCRIPTION_PROBABILITY + self.TEXT_EMBEDDING_PROBABILITY:
            return GPUJobType.TEXT_EMBEDDING
        elif rand_val < self.TRANSCRIPTION_PROBABILITY + self.TEXT_EMBEDDING_PROBABILITY + self.SUMMARIZATION_PROBABILITY:
            return GPUJobType.SUMMARIZATION
        else:
            # Fallback for remaining 10% - pick randomly from available types
            return random.choice([GPUJobType.TRANSCRIPTION, GPUJobType.TEXT_EMBEDDING, GPUJobType.SUMMARIZATION])

    # -------------------------------------------------------------- #
    # Status and Monitoring
    # -------------------------------------------------------------- #

    def get_status(self) -> dict[str, Any]:
        """
        Get current status of GPU resource manager.

        Returns:
            Dictionary with status information
        """
        return {
            "scheduler_running": self._scheduler_running,
            "gpu_lock": self._gpu_lock.get_status(),
            "queue_sizes": {
                "transcription": self._transcription_queue.qsize(),
                "text_embedding": self._text_embedding_queue.qsize(),
                "summarization": self._summarization_queue.qsize(),
                "chatbot": self._chatbot_queue.qsize(),
            },
            "stats": {
                "total_transcription_locks": self._total_transcription_locks,
                "total_text_embedding_locks": self._total_text_embedding_locks,
                "total_summarization_locks": self._total_summarization_locks,
                "total_chatbot_locks": self._total_chatbot_locks,
                "consecutive_transcription": self._consecutive_transcription_count,
                "consecutive_text_embedding": self._consecutive_text_embedding_count,
                "consecutive_summarization": self._consecutive_summarization_count,
                "last_job_type": (self._last_job_type.value if self._last_job_type else None),
            },
        }


# -------------------------------------------------------------- #
# Context Manager for GPU Lock
# -------------------------------------------------------------- #


class _GPULockContext:
    """
    Context manager for GPU lock acquisition and release.

    Usage:
        async with gpu_manager.acquire_lock("transcription"):
            # GPU work here
    """

    def __init__(
        self,
        manager: GPUResourceManager,
        job_type: GPUJobType,
        job_id: str,
        metadata: dict,
    ):
        self.manager = manager
        self.job_type = job_type
        self.job_id = job_id
        self.metadata = metadata

    async def __aenter__(self):
        """Acquire GPU lock when entering context."""
        await self.manager._request_lock(self.job_type, self.job_id, self.metadata)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Release GPU lock when exiting context."""
        await self.manager._release_lock(self.job_type, self.job_id)
        return False
