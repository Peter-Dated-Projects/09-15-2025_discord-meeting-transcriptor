"""
GPU Resource Lock Manager.

This module provides an async lock system for managing exclusive GPU access.
Only one job can hold the GPU lock at a time, ensuring proper resource management.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from source.utils import get_current_timestamp_est


@dataclass
class GPULockInfo:
    """Information about current GPU lock holder."""

    job_id: str
    job_type: str
    acquired_at: datetime
    metadata: dict = field(default_factory=dict)


class GPUResourceLock:
    """
    Async lock for managing GPU resource access.

    This lock ensures that only one job can use the GPU at a time.
    It provides:
    - Async acquire/release operations
    - Lock holder tracking
    - Wait queue visibility
    - Lock status monitoring
    """

    def __init__(self):
        """Initialize the GPU resource lock."""
        self._lock = asyncio.Lock()
        self._current_holder: Optional[GPULockInfo] = None
        self._wait_count = 0

    async def acquire(self, job_id: str, job_type: str, metadata: dict = None) -> None:
        """
        Acquire the GPU lock for a job.

        This will block until the lock is available.

        Args:
            job_id: Unique identifier for the job acquiring the lock
            job_type: Type of job (transcription, summarization, chatbot)
            metadata: Optional metadata about the job
        """
        self._wait_count += 1
        try:
            await self._lock.acquire()
            self._current_holder = GPULockInfo(
                job_id=job_id,
                job_type=job_type,
                acquired_at=get_current_timestamp_est(),
                metadata=metadata or {},
            )
        finally:
            self._wait_count -= 1

    def release(self) -> None:
        """
        Release the GPU lock.

        This should be called after a job completes its GPU work.
        """
        if self._lock.locked():
            self._current_holder = None
            self._lock.release()

    def is_locked(self) -> bool:
        """Check if the GPU lock is currently held."""
        return self._lock.locked()

    def get_current_holder(self) -> Optional[GPULockInfo]:
        """Get information about the current lock holder."""
        return self._current_holder

    def get_wait_count(self) -> int:
        """Get the number of jobs waiting to acquire the lock."""
        return self._wait_count

    def get_status(self) -> dict:
        """
        Get detailed status of the GPU lock.

        Returns:
            Dictionary with lock status information:
            - is_locked: Whether the lock is currently held
            - current_holder: Job ID of current holder (if any)
            - holder_job_type: Type of job holding the lock (if any)
            - acquired_at: Timestamp when lock was acquired (if held)
            - wait_count: Number of jobs waiting for the lock
        """
        holder_info = None
        if self._current_holder:
            holder_info = {
                "job_id": self._current_holder.job_id,
                "job_type": self._current_holder.job_type,
                "acquired_at": self._current_holder.acquired_at.isoformat(),
                "metadata": self._current_holder.metadata,
            }

        return {
            "is_locked": self.is_locked(),
            "current_holder": holder_info,
            "wait_count": self.get_wait_count(),
        }

    async def __aenter__(self):
        """Async context manager entry."""
        await self.acquire("context_manager", "unknown")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        self.release()
        return False
