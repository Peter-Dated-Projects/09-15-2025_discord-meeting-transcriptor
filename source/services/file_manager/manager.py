import asyncio
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

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
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, int] = {}

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        # check if folder exists
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)

        await self.services.logging_service.info(
            f"FileManagerService initialized with storage path: {self.storage_path}"
        )
        return True

    async def on_close(self):
        return True

    # -------------------------------------------------------------- #
    # File Management Methods
    # -------------------------------------------------------------- #

    def _lock_key(self, filename: str) -> str:
        """
        Normalize lock key by absolute path.
        On Windows, also convert to lowercase for case-insensitive comparison.
        """
        p = Path(self.storage_path, filename).resolve()
        return str(p).lower() if sys.platform.startswith("win") else str(p)

    def get_storage_path(self) -> str:
        """Get the storage path."""
        return self.storage_path

    def get_storage_absolute_path(self) -> str:
        """Get the absolute storage path."""
        return os.path.abspath(self.storage_path)

    @asynccontextmanager
    async def _acquire_file_lock(self, filename: str):
        """Context manager for acquiring and releasing file locks safely."""
        key = self._lock_key(filename)
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._waiters[key] = self._waiters.get(key, 0) + 1
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            self._waiters[key] -= 1
            if self._waiters[key] == 0:
                self._locks.pop(key, None)
                self._waiters.pop(key, None)

    async def save_file(self, filename: str, data: bytes) -> None:
        """Save a file to the storage path atomically."""
        if os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileExistsError(f"File {filename} already exists.")

        path = Path(self.storage_path, filename)
        path.parent.mkdir(parents=True, exist_ok=True)

        async with self._acquire_file_lock(filename):
            # write to tmp in the same dir
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = Path(tmp.name)

            # atomic rename on same filesystem
            os.replace(tmp_path, path)

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

    async def create_file(self, filename: str) -> None:
        """Create an empty file in the storage path."""
        async with (
            self._acquire_file_lock(filename),
            aiofiles.open(os.path.join(self.storage_path, filename), "wb") as f,
        ):
            await f.write(b"")

        await self.services.logging_service.info(f"Created empty file: {filename}")

    def ensure_parent_dir(self, filepath: str) -> None:
        """
        Ensure the parent directory of the given filepath exists.
        Creates nested directories if needed.

        Args:
            filepath: Full path to a file (not just filename)
        """
        parent_dir = os.path.dirname(filepath)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

    async def _acquire_file_lock_oneshot(self, filename: str):
        """Acquire a file lock for atomic operations (non-context manager)."""
        key = self._lock_key(filename)
        lock = self._locks.setdefault(key, asyncio.Lock())
        self._waiters[key] = self._waiters.get(key, 0) + 1
        await lock.acquire()

    async def _release_file_lock_oneshot(self, filename: str):
        """Release a file lock (non-context manager)."""
        key = self._lock_key(filename)
        if key in self._locks:
            self._locks[key].release()
            self._waiters[key] -= 1
            if self._waiters[key] == 0:
                self._locks.pop(key, None)
                self._waiters.pop(key, None)
