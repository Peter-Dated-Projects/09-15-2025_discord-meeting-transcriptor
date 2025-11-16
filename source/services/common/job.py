"""
Common job and job queue implementation for event-based processing.

This module provides:
- Job: Base class for defining asynchronous jobs
- JobQueue: Event-based queue that processes one job at a time
- JobStatus: Enum for tracking job states
"""

import asyncio
import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Generic, TypeVar

from source.utils import get_current_timestamp_est


class JobStatus(enum.Enum):
    """Status of a job in the queue."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job(ABC):
    """
    Base class for a job that can be processed by a JobQueue.

    Attributes:
        job_id: Unique identifier for the job
        created_at: Timestamp when the job was created
        started_at: Timestamp when the job started processing (None if not started)
        finished_at: Timestamp when the job finished (None if not finished)
        status: Current status of the job
        error_message: Error message if the job failed (None if no error)
        metadata: Additional metadata for the job
    """

    job_id: str
    created_at: datetime = field(default_factory=get_current_timestamp_est)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    status: JobStatus = JobStatus.PENDING
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @abstractmethod
    async def execute(self) -> None:
        """
        Execute the job's main logic.

        This method should be implemented by subclasses to define
        what the job actually does when processed.

        Raises:
            Exception: Any exception raised during execution will be caught
                      by the JobQueue and marked as a failure.
        """
        pass

    def mark_started(self) -> None:
        """Mark the job as started."""
        self.started_at = get_current_timestamp_est()
        self.status = JobStatus.IN_PROGRESS

    def mark_completed(self) -> None:
        """Mark the job as completed."""
        self.finished_at = get_current_timestamp_est()
        self.status = JobStatus.COMPLETED

    def mark_failed(self, error_message: str) -> None:
        """Mark the job as failed with an error message."""
        self.finished_at = get_current_timestamp_est()
        self.status = JobStatus.FAILED
        self.error_message = error_message

    def mark_cancelled(self) -> None:
        """Mark the job as cancelled."""
        self.finished_at = get_current_timestamp_est()
        self.status = JobStatus.CANCELLED


TJob = TypeVar("TJob", bound=Job)


class JobQueue(Generic[TJob]):
    """
    Event-based job queue that processes one job at a time.

    The queue is idle by default and activates when jobs are added.
    Jobs are processed sequentially in FIFO order. The queue supports:
    - Adding jobs dynamically
    - Callback notifications on job completion/failure
    - Graceful shutdown
    - Status monitoring

    Attributes:
        max_retries: Maximum number of retry attempts for failed jobs (default: 0)
        on_job_complete: Optional callback when a job completes successfully
        on_job_failed: Optional callback when a job fails
        on_job_started: Optional callback when a job starts
    """

    def __init__(
        self,
        max_retries: int = 0,
        on_job_complete: Callable[[TJob], Any] | None = None,
        on_job_failed: Callable[[TJob], Any] | None = None,
        on_job_started: Callable[[TJob], Any] | None = None,
    ):
        """
        Initialize the job queue.

        Args:
            max_retries: Maximum number of retry attempts for failed jobs
            on_job_complete: Optional callback when a job completes successfully
            on_job_failed: Optional callback when a job fails
            on_job_started: Optional callback when a job starts
        """
        self._queue: asyncio.Queue[TJob] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._is_running: bool = False
        self._shutdown_event: asyncio.Event = asyncio.Event()
        self._max_retries: int = max_retries
        self._retry_counts: dict[str, int] = {}

        # Callbacks
        self._on_job_complete = on_job_complete
        self._on_job_failed = on_job_failed
        self._on_job_started = on_job_started

        # Statistics
        self._total_jobs_processed: int = 0
        self._total_jobs_failed: int = 0
        self._current_job: TJob | None = None

    async def add_job(self, job: TJob) -> None:
        """
        Add a job to the queue.

        If the worker is not running, it will be started automatically.

        Args:
            job: The job to add to the queue
        """
        await self._queue.put(job)

        # Start the worker if not already running
        if not self._is_running:
            await self.start()

    async def start(self) -> None:
        """Start the job queue worker."""
        if self._is_running:
            return

        self._is_running = True
        self._shutdown_event.clear()
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self, wait_for_completion: bool = True) -> None:
        """
        Stop the job queue worker.

        Args:
            wait_for_completion: If True, wait for current job to complete before stopping
        """
        if not self._is_running:
            return

        self._is_running = False
        self._shutdown_event.set()

        if wait_for_completion and self._worker_task:
            await self._worker_task

        self._worker_task = None

    async def _worker(self) -> None:
        """
        Main worker loop that processes jobs from the queue.

        This runs continuously until shutdown is requested.
        """
        while self._is_running:
            try:
                # Wait for a job with timeout to allow shutdown checks
                try:
                    job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Check if we should shutdown when queue is empty
                    if self._shutdown_event.is_set():
                        break
                    continue

                # Process the job
                self._current_job = job
                await self._process_job(job)
                self._current_job = None

                # Mark task as done
                self._queue.task_done()

                # If queue is empty and we're in auto-shutdown mode, stop the worker
                if self._queue.empty() and not self._shutdown_event.is_set():
                    # Queue is empty, keep running but idle
                    pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log unexpected errors but keep worker running
                print(f"Unexpected error in job queue worker: {e}")

    async def _process_job(self, job: TJob) -> None:
        """
        Process a single job with error handling and retries.

        Args:
            job: The job to process
        """
        retry_count = self._retry_counts.get(job.job_id, 0)

        try:
            # Mark job as started
            job.mark_started()

            # Call started callback
            if self._on_job_started:
                try:
                    result = self._on_job_started(job)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    print(f"Error in on_job_started callback: {e}")

            # Execute the job
            await job.execute()

            # Mark job as completed
            job.mark_completed()
            self._total_jobs_processed += 1

            # Clean up retry count
            if job.job_id in self._retry_counts:
                del self._retry_counts[job.job_id]

            # Call completion callback
            if self._on_job_complete:
                try:
                    result = self._on_job_complete(job)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    print(f"Error in on_job_complete callback: {e}")

        except Exception as e:
            error_message = f"{type(e).__name__}: {str(e)}"

            # Check if we should retry
            if retry_count < self._max_retries:
                self._retry_counts[job.job_id] = retry_count + 1
                # Re-queue the job for retry
                await self._queue.put(job)
                # Reset job status for retry
                job.status = JobStatus.PENDING
                job.error_message = None
            else:
                # Mark job as failed
                job.mark_failed(error_message)
                self._total_jobs_failed += 1

                # Clean up retry count
                if job.job_id in self._retry_counts:
                    del self._retry_counts[job.job_id]

                # Call failed callback
                if self._on_job_failed:
                    try:
                        result = self._on_job_failed(job)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as e:
                        print(f"Error in on_job_failed callback: {e}")

    def get_queue_size(self) -> int:
        """Get the current number of jobs waiting in the queue."""
        return self._queue.qsize()

    def get_current_job(self) -> TJob | None:
        """Get the currently processing job, if any."""
        return self._current_job

    def get_statistics(self) -> dict[str, Any]:
        """
        Get queue statistics.

        Returns:
            Dictionary with statistics including:
            - is_running: Whether the worker is active
            - queue_size: Number of pending jobs
            - total_processed: Total jobs completed
            - total_failed: Total jobs failed
            - current_job_id: ID of current job (if any)
        """
        return {
            "is_running": self._is_running,
            "queue_size": self.get_queue_size(),
            "total_processed": self._total_jobs_processed,
            "total_failed": self._total_jobs_failed,
            "current_job_id": self._current_job.job_id if self._current_job else None,
            "current_job_status": (self._current_job.status.value if self._current_job else None),
        }

    async def wait_until_empty(self) -> None:
        """Wait until all jobs in the queue are processed."""
        await self._queue.join()

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return self._queue.empty()

    def is_running(self) -> bool:
        """Check if the worker is running."""
        return self._is_running
