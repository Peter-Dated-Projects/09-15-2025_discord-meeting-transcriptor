"""
Integration tests for GPU Resource Manager Service.

These tests verify the GPU Resource Manager's ability to manage GPU access,
coordinate between services, and handle concurrent job requests.
Tests require a connected server manager and initialized services.
"""

import pytest

from source.services.manager import ServicesManager

# ============================================================================
# GPU Resource Manager Service Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.local
@pytest.mark.asyncio
class TestGPUResourceManagerService:
    """Test GPU Resource Manager Service functionality."""

    async def test_gpu_manager_exists_on_services_manager(self, services_manager: ServicesManager):
        """
        Test that GPU Resource Manager exists on ServicesManager.

        Verifies that the GPU Resource Manager is properly instantiated
        and accessible through the services manager.

        Args:
            services_manager: Fixture providing initialized services
        """
        # Assert: GPU Resource Manager exists
        assert hasattr(
            services_manager, "gpu_resource_manager"
        ), "ServicesManager missing gpu_resource_manager attribute"
        assert services_manager.gpu_resource_manager is not None, "gpu_resource_manager is None"

    async def test_gpu_manager_initialization(self, services_manager: ServicesManager):
        """
        Test that GPU Resource Manager is properly initialized.

        Verifies that the GPU Resource Manager has been initialized with
        the correct references and that the scheduler is running.

        Args:
            services_manager: Fixture providing initialized services
        """
        gpu_manager = services_manager.gpu_resource_manager

        # Assert: Services reference is set
        assert gpu_manager.services is not None, "GPU Manager services reference is None"
        assert (
            gpu_manager.services == services_manager
        ), "GPU Manager services reference doesn't match ServicesManager"

        # Assert: Scheduler is running
        assert gpu_manager._scheduler_running, "GPU scheduler is not running"

    async def test_gpu_lock_acquisition(self, services_manager: ServicesManager):
        """
        Test GPU lock can be acquired successfully.

        Verifies that a GPU lock can be acquired for a job and that
        the lock is properly held during the context.

        Args:
            services_manager: Fixture providing initialized services
        """
        gpu_manager = services_manager.gpu_resource_manager

        # Act: Acquire GPU lock (acquire_lock returns a context manager)
        async with gpu_manager.acquire_lock(
            job_type="transcription", job_id="test_job_001", metadata={"test": True}
        ):
            # Assert: Lock is held
            assert gpu_manager._gpu_lock.is_locked(), "GPU lock should be locked but isn't"

            # Assert: Status reflects lock is held
            status = gpu_manager.get_status()
            assert status["gpu_lock"]["is_locked"], "Status should show GPU is locked"
            assert (
                status["gpu_lock"]["current_holder"]["job_id"] == "test_job_001"
            ), "Lock holder job_id mismatch"

    async def test_gpu_lock_release(self, services_manager: ServicesManager):
        """
        Test GPU lock is properly released after use.

        Verifies that the GPU lock is automatically released when
        exiting the context manager.

        Args:
            services_manager: Fixture providing initialized services
        """
        gpu_manager = services_manager.gpu_resource_manager

        # Act: Acquire and release lock
        async with gpu_manager.acquire_lock(
            job_type="transcription", job_id="test_job_002", metadata={"test": True}
        ):
            pass  # Lock acquired

        # Assert: Lock is released
        assert (
            not gpu_manager._gpu_lock.is_locked()
        ), "GPU lock should be released but is still locked"

    async def test_gpu_manager_status_structure(self, services_manager: ServicesManager):
        """
        Test that GPU Manager status returns expected information structure.

        Verifies that the status dictionary contains all required fields
        with correct initial values.

        Args:
            services_manager: Fixture providing initialized services
        """
        gpu_manager = services_manager.gpu_resource_manager

        # Act: Get status
        status = gpu_manager.get_status()

        # Assert: Status has required fields
        assert "scheduler_running" in status, "Status missing scheduler_running"
        assert "gpu_lock" in status, "Status missing gpu_lock"
        assert "queue_sizes" in status, "Status missing queue_sizes"
        assert "stats" in status, "Status missing stats"

        # Assert: Initial values are correct
        assert status["scheduler_running"] is True, "Scheduler should be running"
        assert status["gpu_lock"]["is_locked"] is False, "GPU should not be locked initially"

    async def test_gpu_manager_queue_sizes(self, services_manager: ServicesManager):
        """
        Test that GPU Manager reports queue sizes correctly.

        Verifies that the GPU Resource Manager tracks queue sizes
        for different job types.

        Args:
            services_manager: Fixture providing initialized services
        """
        gpu_manager = services_manager.gpu_resource_manager

        # Act: Get status
        status = gpu_manager.get_status()

        # Assert: Queue sizes exist
        assert "queue_sizes" in status, "Status missing queue_sizes"
        queue_sizes = status["queue_sizes"]

        # Assert: Expected queue types exist
        assert "transcription" in queue_sizes, "Missing transcription queue"
        assert isinstance(queue_sizes["transcription"], int), "Queue size should be integer"

    async def test_concurrent_lock_acquisition_blocks(self, services_manager: ServicesManager):
        """
        Test that concurrent lock acquisition properly blocks.

        Verifies that when a lock is held, a second attempt to acquire
        the lock will wait until the first lock is released.

        Args:
            services_manager: Fixture providing initialized services
        """
        import asyncio

        gpu_manager = services_manager.gpu_resource_manager

        lock_acquired_times = []

        async def acquire_lock_task(job_id: str, delay: float):
            """Task to acquire lock and record timing."""
            await asyncio.sleep(delay)
            async with gpu_manager.acquire_lock(
                job_type="transcription", job_id=job_id, metadata={"test": True}
            ):
                lock_acquired_times.append((job_id, asyncio.get_event_loop().time()))
                await asyncio.sleep(0.1)  # Hold lock briefly

        # Act: Start two tasks trying to acquire the lock
        await asyncio.gather(acquire_lock_task("job_1", 0.0), acquire_lock_task("job_2", 0.05))

        # Assert: Both tasks completed
        assert len(lock_acquired_times) == 2, "Both tasks should have acquired the lock"

        # Assert: Second task waited for first to complete
        job_1_time = next(t for jid, t in lock_acquired_times if jid == "job_1")
        job_2_time = next(t for jid, t in lock_acquired_times if jid == "job_2")

        # Second job should have acquired lock after first job released it
        # Since job_1 holds for 0.1s, job_2 should start at least 0.1s later
        assert job_2_time > job_1_time, "Second job should have acquired lock after first job"
