import asyncio
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    from source.context import Context

from source.services.manager import BaseFileServiceManager

# -------------------------------------------------------------- #
# File Manager Service
# -------------------------------------------------------------- #


class FileManagerService(BaseFileServiceManager):
    """Service for managing file storage and retrieval."""

    def __init__(self, context: "Context", storage_path: str):
        super().__init__(context)

        self.storage_path = storage_path

        # create atomic file writing system
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, int] = {}

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)

        # Run blocking filesystem operations in executor
        loop = asyncio.get_event_loop()

        # check if folder exists
        if not await loop.run_in_executor(None, os.path.exists, self.storage_path):
            await loop.run_in_executor(None, os.makedirs, self.storage_path)

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
        file_path = os.path.join(self.storage_path, filename)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileExistsError(f"File {filename} already exists.")

        path = Path(self.storage_path, filename)

        # Run blocking mkdir in executor
        await loop.run_in_executor(None, path.parent.mkdir, True, True)

        async with self._acquire_file_lock(filename):
            # Create temp file in executor
            def write_temp_file():
                with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                    tmp.write(data)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    tmp_path = Path(tmp.name)
                return tmp_path

            tmp_path = await loop.run_in_executor(None, write_temp_file)

            # atomic rename on same filesystem (non-blocking)
            await loop.run_in_executor(None, os.replace, tmp_path, path)

        await self.services.logging_service.info(f"Saved file: {filename} ({len(data)} bytes)")

    async def read_file(self, filename: str) -> bytes:
        """Read a file from the storage path."""
        file_path = os.path.join(self.storage_path, filename)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileNotFoundError(f"File {filename} does not exist.")

        async with (
            self._acquire_file_lock(filename),
            aiofiles.open(file_path, "rb") as f,
        ):
            data = await f.read()

        await self.services.logging_service.info(f"Read file: {filename} ({len(data)} bytes)")
        return data

    async def delete_file(self, filename: str) -> None:
        """Delete a file from the storage path."""
        file_path = os.path.join(self.storage_path, filename)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileNotFoundError(f"File {filename} does not exist.")

        async with self._acquire_file_lock(filename):
            await loop.run_in_executor(None, os.remove, file_path)

        await self.services.logging_service.info(f"Deleted file: {filename}")

    async def update_file(self, filename: str, data: bytes) -> None:
        """Update a file in the storage path."""
        file_path = os.path.join(self.storage_path, filename)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileNotFoundError(f"File {filename} does not exist.")

        async with (
            self._acquire_file_lock(filename),
            aiofiles.open(file_path, "wb") as f,
        ):
            await f.write(data)

        await self.services.logging_service.info(f"Updated file: {filename} ({len(data)} bytes)")

    async def get_folder_contents(self) -> list[str]:
        """Get a list of files in the storage path."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, os.listdir, self.storage_path)

    async def file_exists(self, filename: str) -> bool:
        """Check if a file exists in the storage path."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, os.path.exists, os.path.join(self.storage_path, filename)
        )

    async def create_file(self, filename: str) -> None:
        """Create an empty file in the storage path."""
        async with (
            self._acquire_file_lock(filename),
            aiofiles.open(os.path.join(self.storage_path, filename), "wb") as f,
        ):
            await f.write(b"")

        await self.services.logging_service.info(f"Created empty file: {filename}")

    async def ensure_parent_dir(self, filepath: str) -> None:
        """
        Ensure the parent directory of the given filepath exists.
        Creates nested directories if needed.

        Args:
            filepath: Full path to a file (not just filename)
        """
        parent_dir = os.path.dirname(filepath)
        if parent_dir:
            loop = asyncio.get_event_loop()
            exists = await loop.run_in_executor(None, os.path.exists, parent_dir)
            if not exists:
                await loop.run_in_executor(None, os.makedirs, parent_dir, True)

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
