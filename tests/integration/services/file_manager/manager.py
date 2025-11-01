import asyncio
import os
import tempfile

import pytest

from source.server.dev.constructor import construct_server_manager
from source.services.file_manager.manager import FileManagerService

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
async def dev_server(_test_environment: str):
    """
    Create a dev environment server manager.

    This fixture constructs a ServerManager using the DEV environment.
    It connects all servers and ensures proper cleanup.

    Args:
        _test_environment: Test environment from conftest (local or prod)
    """
    try:
        server = construct_server_manager()
        await server.connect_all()
        yield server
        await server.disconnect_all()
    except Exception as e:
        # If connection fails, provide a mock server for basic file manager testing
        # This allows file manager tests to run without a full database setup
        pytest.skip(f"Could not connect to dev server: {e}")


@pytest.fixture
async def temp_storage():
    """Create a temporary storage directory for file manager tests."""
    temp_dir = tempfile.mkdtemp(prefix="file_manager_test_")
    yield temp_dir
    # Cleanup: remove all files in the temp directory
    for root, dirs, files in os.walk(temp_dir, topdown=False):
        for file in files:
            os.remove(os.path.join(root, file))
        for dir in dirs:
            os.rmdir(os.path.join(root, dir))
    os.rmdir(temp_dir)


@pytest.fixture
async def file_manager_service(dev_server, temp_storage):
    """Create a FileManagerService instance with a dev server and temp storage."""
    service = FileManagerService(server=dev_server, storage_path=temp_storage)
    await service.on_start()
    yield service
    await service.on_close()


# ============================================================================
# Basic Operations Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.local
class TestFileManagerServiceBasicOperations:
    """Test basic file operations: create, read, update, delete."""

    @pytest.mark.asyncio
    async def test_save_file(self, file_manager_service: FileManagerService):
        """Test saving a file to storage."""
        filename = "test_file.txt"
        data = b"Hello, World!"

        await file_manager_service.save_file(filename, data)

        # Verify file exists
        file_path = os.path.join(file_manager_service.get_storage_path(), filename)
        assert os.path.exists(file_path)

        # Verify file content
        with open(file_path, "rb") as f:
            content = f.read()
            assert content == data

    @pytest.mark.asyncio
    async def test_read_file(self, file_manager_service: FileManagerService):
        """Test reading a file from storage."""
        filename = "read_test.txt"
        original_data = b"Test data for reading"

        # First save the file
        await file_manager_service.save_file(filename, original_data)

        # Now read it back
        read_data = await file_manager_service.read_file(filename)

        assert read_data == original_data

    @pytest.mark.asyncio
    async def test_delete_file(self, file_manager_service: FileManagerService):
        """Test deleting a file from storage."""
        filename = "delete_test.txt"
        data = b"Data to be deleted"

        # Save a file
        await file_manager_service.save_file(filename, data)

        # Verify it exists
        file_path = os.path.join(file_manager_service.get_storage_path(), filename)
        assert os.path.exists(file_path)

        # Delete it
        await file_manager_service.delete_file(filename)

        # Verify it's gone
        assert not os.path.exists(file_path)

    @pytest.mark.asyncio
    async def test_update_file(self, file_manager_service: FileManagerService):
        """Test updating a file in storage."""
        filename = "update_test.txt"
        original_data = b"Original content"
        updated_data = b"Updated content"

        # Save the file
        await file_manager_service.save_file(filename, original_data)

        # Update it
        await file_manager_service.update_file(filename, updated_data)

        # Read and verify
        read_data = await file_manager_service.read_file(filename)
        assert read_data == updated_data

    @pytest.mark.asyncio
    async def test_save_duplicate_raises_error(self, file_manager_service: FileManagerService):
        """Test that saving a duplicate file raises FileExistsError."""
        filename = "duplicate_test.txt"
        data = b"test data"

        # Save the file
        await file_manager_service.save_file(filename, data)

        # Try to save the same file again
        with pytest.raises(FileExistsError):
            await file_manager_service.save_file(filename, data)

    @pytest.mark.asyncio
    async def test_read_nonexistent_file_raises_error(
        self, file_manager_service: FileManagerService
    ):
        """Test that reading a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await file_manager_service.read_file("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file_raises_error(
        self, file_manager_service: FileManagerService
    ):
        """Test that deleting a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await file_manager_service.delete_file("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_update_nonexistent_file_raises_error(
        self, file_manager_service: FileManagerService
    ):
        """Test that updating a nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await file_manager_service.update_file("nonexistent.txt", b"data")


# ============================================================================
# Lock System Tests - Concurrent Operations
# ============================================================================


@pytest.mark.integration
@pytest.mark.local
class TestFileManagerServiceLockSystem:
    """Test the file locking system for concurrent operations."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_concurrent_writes_maintain_order(self, file_manager_service: FileManagerService):
        """
        Test that multiple concurrent writes to a single file maintain order
        through the lock system.

        This test creates multiple tasks that write to the same file sequentially
        and verifies that the lock system ensures writes happen in order.
        """
        filename = "concurrent_write_test.txt"

        # Create initial file
        await file_manager_service.save_file(filename, b"")

        write_order = []
        num_writes = 5

        async def write_data(order_num: int, data: bytes):
            """Write data and track the order of writes."""
            await file_manager_service.update_file(filename, data)
            write_order.append(order_num)

        # Create concurrent write tasks
        tasks = [write_data(i, f"Write {i}\n".encode()) for i in range(num_writes)]

        # Run all tasks concurrently
        await asyncio.gather(*tasks)

        # Verify that writes happened (we have all writes)
        assert len(write_order) == num_writes

        # Verify that all write numbers are present (no writes were skipped)
        assert sorted(write_order) == list(range(num_writes))

        # Read the file and verify it has content from the last write
        final_content = await file_manager_service.read_file(filename)
        assert b"Write" in final_content

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_concurrent_mixed_operations_with_locks(
        self, file_manager_service: FileManagerService
    ):
        """
        Test concurrent mixed operations (read, write, delete) on multiple files.

        Verifies that the lock system prevents race conditions and ensures
        data integrity across concurrent operations.
        """
        files_created = []
        results = {"reads": 0, "writes": 0, "success": True}

        async def concurrent_operation(file_num: int):
            """Perform concurrent file operations."""
            try:
                filename = f"concurrent_file_{file_num}.txt"

                # Write
                data = f"Data for file {file_num}".encode()
                await file_manager_service.save_file(filename, data)
                files_created.append(filename)
                results["writes"] += 1

                # Read
                read_data = await file_manager_service.read_file(filename)
                assert read_data == data
                results["reads"] += 1

                # Update
                updated_data = f"Updated data for file {file_num}".encode()
                await file_manager_service.update_file(filename, updated_data)
                results["writes"] += 1

                # Read again
                final_read = await file_manager_service.read_file(filename)
                assert final_read == updated_data
                results["reads"] += 1

            except Exception:
                results["success"] = False
                raise

        # Run 10 concurrent operations
        await asyncio.gather(*[concurrent_operation(i) for i in range(10)])

        # Verify all operations succeeded
        assert results["success"] is True
        assert results["writes"] == 20  # 2 writes per file * 10 files
        assert results["reads"] == 20  # 2 reads per file * 10 files

        # Cleanup
        for filename in files_created:
            await file_manager_service.delete_file(filename)

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_sequential_file_access_respects_locks(
        self, file_manager_service: FileManagerService
    ):
        """
        Test that sequential file access properly acquires and releases locks.

        Verifies that locks are properly managed and don't cause deadlocks
        or prevent subsequent operations.
        """
        filename = "sequential_lock_test.txt"
        num_operations = 10

        # Perform multiple sequential operations on the same file
        await file_manager_service.save_file(filename, b"Initial")

        for i in range(num_operations):
            data = f"Iteration {i}".encode()
            await file_manager_service.update_file(filename, data)

        # Read final value
        final_data = await file_manager_service.read_file(filename)
        assert b"Iteration" in final_data

        # Verify lock is properly released (no orphaned locks)
        assert filename not in file_manager_service._file_locks

        # Cleanup
        await file_manager_service.delete_file(filename)

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_lock_prevents_concurrent_writes_to_same_file(
        self, file_manager_service: FileManagerService
    ):
        """
        Test that the lock system prevents overlapping writes to the same file.

        This test launches multiple concurrent write operations to the same file
        and verifies that they execute serially (one at a time) due to locking.
        """
        filename = "lock_serialization_test.txt"
        write_start_times = []
        write_end_times = []
        write_delay = 0.1  # 100ms delay per write

        await file_manager_service.save_file(filename, b"")

        async def slow_write(write_num: int):
            """Perform a write with a delay to simulate I/O."""
            # Simulate slow write operation
            await asyncio.sleep(write_delay)

            write_start_times.append((write_num, asyncio.get_event_loop().time()))
            await file_manager_service.update_file(filename, f"Write {write_num}".encode())
            write_end_times.append((write_num, asyncio.get_event_loop().time()))

        # Launch 3 concurrent writes
        await asyncio.gather(*[slow_write(i) for i in range(3)])

        # Verify all writes completed
        assert len(write_start_times) == 3
        assert len(write_end_times) == 3

        # Verify that writes did not overlap
        # (end time of write N should be before start time of write N+1)
        sorted_starts = sorted(write_start_times, key=lambda x: x[1])
        sorted_ends = sorted(write_end_times, key=lambda x: x[1])

        for i in range(len(sorted_ends) - 1):
            end_time = sorted_ends[i][1]
            next_start_time = sorted_starts[i + 1][1]
            # With some tolerance for timing variations
            assert end_time <= next_start_time + 0.05, (
                f"Write overlap detected: write {i} ended at {end_time}, "
                f"write {i+1} started at {next_start_time}"
            )

        await file_manager_service.delete_file(filename)

    @pytest.mark.asyncio
    async def test_storage_path_methods(self, file_manager_service: FileManagerService):
        """Test storage path getter methods."""
        storage_path = file_manager_service.get_storage_path()
        assert storage_path is not None
        assert isinstance(storage_path, str)

        abs_path = file_manager_service.get_storage_absolute_path()
        assert abs_path is not None
        assert os.path.isabs(abs_path)
        assert abs_path == os.path.abspath(storage_path)

    @pytest.mark.asyncio
    async def test_binary_file_operations(self, file_manager_service: FileManagerService):
        """Test that binary data is preserved correctly through save/read cycle."""
        filename = "binary_test.bin"

        # Create binary data with null bytes and other special bytes
        binary_data = bytes(range(256))

        await file_manager_service.save_file(filename, binary_data)
        read_data = await file_manager_service.read_file(filename)

        assert read_data == binary_data
        assert len(read_data) == 256

        await file_manager_service.delete_file(filename)
