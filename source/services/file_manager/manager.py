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

    def _lock_key(self, filepath: str) -> str:
        """
        Normalize lock key by absolute path.
        On Windows, also convert to lowercase for case-insensitive comparison.

        Args:
            filepath: Can be either absolute path or relative to storage_path
        """
        # If it's already an absolute path, use it directly
        if os.path.isabs(filepath):
            p = Path(filepath).resolve()
        else:
            # Otherwise, treat as relative to storage_path
            p = Path(self.storage_path, filepath).resolve()
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

    # -------------------------------------------------------------- #
    # Public File Operations
    # -------------------------------------------------------------- #

    async def save_file(self, filepath: str, data: bytes) -> None:
        """
        Save a file atomically.

        Args:
            filepath: Can be absolute path or relative to storage_path
            data: File data as bytes

        Raises:
            FileExistsError: If file already exists
        """
        # Determine if path is absolute or relative
        if os.path.isabs(filepath):
            file_path = filepath
            path = Path(filepath)
        else:
            file_path = os.path.join(self.storage_path, filepath)
            path = Path(self.storage_path, filepath)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileExistsError(f"File {filepath} already exists.")

        # Ensure parent directory exists
        def ensure_dir():
            path.parent.mkdir(parents=True, exist_ok=True)

        await loop.run_in_executor(None, ensure_dir)

        async with self._acquire_file_lock(filepath):
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

        await self.services.logging_service.info(f"Saved file: {filepath} ({len(data)} bytes)")

    async def read_file(self, filepath: str) -> bytes:
        """
        Read a file.

        Args:
            filepath: Can be absolute path or relative to storage_path

        Returns:
            File contents as bytes

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        # Determine if path is absolute or relative
        if os.path.isabs(filepath):
            file_path = filepath
        else:
            file_path = os.path.join(self.storage_path, filepath)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileNotFoundError(f"File {filepath} does not exist.")

        async with (
            self._acquire_file_lock(filepath),
            aiofiles.open(file_path, "rb") as f,
        ):
            data = await f.read()

        await self.services.logging_service.info(f"Read file: {filepath} ({len(data)} bytes)")
        return data

    async def delete_file(self, filepath: str) -> None:
        """
        Delete a file.

        Args:
            filepath: Can be absolute path or relative to storage_path

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        # Determine if path is absolute or relative
        if os.path.isabs(filepath):
            file_path = filepath
        else:
            file_path = os.path.join(self.storage_path, filepath)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileNotFoundError(f"File {filepath} does not exist.")

        async with self._acquire_file_lock(filepath):
            await loop.run_in_executor(None, os.remove, file_path)

        await self.services.logging_service.info(f"Deleted file: {filepath}")

    async def update_file(self, filepath: str, data: bytes) -> None:
        """
        Update a file.

        Args:
            filepath: Can be absolute path or relative to storage_path
            data: New file data as bytes

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        # Determine if path is absolute or relative
        if os.path.isabs(filepath):
            file_path = filepath
        else:
            file_path = os.path.join(self.storage_path, filepath)

        # Run blocking os.path.exists in executor
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, file_path):
            raise FileNotFoundError(f"File {filepath} does not exist.")

        async with (
            self._acquire_file_lock(filepath),
            aiofiles.open(file_path, "wb") as f,
        ):
            await f.write(data)

        await self.services.logging_service.info(f"Updated file: {filepath} ({len(data)} bytes)")

    async def get_folder_contents(self) -> list[str]:
        """Get a list of files in the storage path."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, os.listdir, self.storage_path)

    async def file_exists(self, filepath: str) -> bool:
        """
        Check if a file exists.

        Args:
            filepath: Can be absolute path or relative to storage_path

        Returns:
            True if file exists, False otherwise
        """
        # Determine if path is absolute or relative
        if os.path.isabs(filepath):
            file_path = filepath
        else:
            file_path = os.path.join(self.storage_path, filepath)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, os.path.exists, file_path)

    async def create_file(self, filepath: str) -> None:
        """
        Create an empty file.

        Args:
            filepath: Can be absolute path or relative to storage_path
        """
        # Determine if path is absolute or relative
        if os.path.isabs(filepath):
            file_path = filepath
        else:
            file_path = os.path.join(self.storage_path, filepath)

        async with (
            self._acquire_file_lock(filepath),
            aiofiles.open(file_path, "wb") as f,
        ):
            await f.write(b"")

        await self.services.logging_service.info(f"Created empty file: {filepath}")

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
