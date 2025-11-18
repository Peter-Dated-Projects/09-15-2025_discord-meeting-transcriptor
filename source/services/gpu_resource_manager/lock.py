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
        self._current_holder: Optional[GPULockInfo] = None

    def acquire(self, job_id: str, job_type: str, metadata: dict = None) -> None:
        """
        Acquire the GPU lock for a job.

        Note: This should only be called after the scheduler grants permission.
        The actual blocking/waiting is handled by the GPUResourceManager scheduler.

        Args:
            job_id: Unique identifier for the job acquiring the lock
            job_type: Type of job (transcription, summarization, chatbot)
            metadata: Optional metadata about the job
        """
        if self._current_holder is not None:
            raise RuntimeError(
                f"GPU lock already held by {self._current_holder.job_id}. "
                f"Cannot acquire for {job_id}. This indicates a scheduler bug."
            )

        self._current_holder = GPULockInfo(
            job_id=job_id,
            job_type=job_type,
            acquired_at=get_current_timestamp_est(),
            metadata=metadata or {},
        )

    def release(self) -> None:
        """
        Release the GPU lock.

        This should be called after a job completes its GPU work.
        """
        self._current_holder = None

    def is_locked(self) -> bool:
        """Check if the GPU lock is currently held."""
        return self._current_holder is not None

    def get_current_holder(self) -> Optional[GPULockInfo]:
        """Get information about the current lock holder."""
        return self._current_holder

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
        }
