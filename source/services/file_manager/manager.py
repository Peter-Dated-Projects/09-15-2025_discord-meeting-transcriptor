import asyncio
import os
from contextlib import asynccontextmanager

import aiofiles

from source.server.server import ServerManager
from source.services.manager import BaseFileServiceManager

# -------------------------------------------------------------- #
# File Manager Service
# -------------------------------------------------------------- #


class FileManagerService(BaseFileServiceManager):
    """Service for managing file storage and retrieval."""

    def __init__(self, server: ServerManager, storage_path: str):
        super().__init__(server)

        self.storage_path = storage_path

        # create atomic file writing system
        self._file_locks = {}
        self._file_lock_counts = {}  # Track number of waiters per lock

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self):
        # check if folder exists
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)
        
        await self.services.logging_service.info(f"FileManagerService initialized with storage path: {self.storage_path}")
        return True

    async def on_close(self):
        return True

    # -------------------------------------------------------------- #
    # File Management Methods
    # -------------------------------------------------------------- #

    def get_storage_path(self) -> str:
        """Get the storage path."""
        return self.storage_path

    def get_storage_absolute_path(self) -> str:
        """Get the absolute storage path."""
        return os.path.abspath(self.storage_path)

    @asynccontextmanager
    async def _acquire_file_lock(self, filename: str):
        """Context manager for acquiring and releasing file locks safely."""
        # Create lock if it doesn't exist and increment reference count
        if filename not in self._file_locks:
            self._file_locks[filename] = asyncio.Lock()
            self._file_lock_counts[filename] = 0

        self._file_lock_counts[filename] += 1
        lock = self._file_locks[filename]

        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            # Decrement reference count and clean up if no one is using it
            self._file_lock_counts[filename] -= 1
            if self._file_lock_counts[filename] == 0:
                del self._file_locks[filename]
                del self._file_lock_counts[filename]

    async def save_file(self, filename: str, data: bytes) -> None:
        """Save a file to the storage path."""
        if os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileExistsError(f"File {filename} already exists.")

        async with (
            self._acquire_file_lock(filename),
            aiofiles.open(os.path.join(self.storage_path, filename), "wb") as f,
        ):
            await f.write(data)
        
        await self.services.logging_service.info(f"Saved file: {filename} ({len(data)} bytes)")

    async def read_file(self, filename: str) -> bytes:
        """Read a file from the storage path."""
        if not os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileNotFoundError(f"File {filename} does not exist.")

        async with (
            self._acquire_file_lock(filename),
            aiofiles.open(os.path.join(self.storage_path, filename), "rb") as f,
        ):
            data = await f.read()
        
        await self.services.logging_service.info(f"Read file: {filename} ({len(data)} bytes)")
        return data

    async def delete_file(self, filename: str) -> None:
        """Delete a file from the storage path."""
        if not os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileNotFoundError(f"File {filename} does not exist.")

        async with self._acquire_file_lock(filename):
            os.remove(os.path.join(self.storage_path, filename))
        
        await self.services.logging_service.info(f"Deleted file: {filename}")

    async def update_file(self, filename: str, data: bytes) -> None:
        """Update a file in the storage path."""
        if not os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileNotFoundError(f"File {filename} does not exist.")

        async with (
            self._acquire_file_lock(filename),
            aiofiles.open(os.path.join(self.storage_path, filename), "wb") as f,
        ):
            await f.write(data)
        
        await self.services.logging_service.info(f"Updated file: {filename} ({len(data)} bytes)")

    async def get_folder_contents(self) -> list[str]:
        """Get a list of files in the storage path."""
        return os.listdir(self.storage_path)

    async def file_exists(self, filename: str) -> bool:
        """Check if a file exists in the storage path."""
        return os.path.exists(os.path.join(self.storage_path, filename))
