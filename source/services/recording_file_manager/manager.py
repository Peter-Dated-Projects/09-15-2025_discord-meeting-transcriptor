from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from source.server.server import ServerManager
from source.services.manager import Manager, ServicesManager

# -------------------------------------------------------------- #
# Recording File Manager Service
# -------------------------------------------------------------- #


class RecordingFileManagerService(Manager):
    """Service for managing recording files."""

    def __init__(self, server: ServerManager, services: ServicesManager, storage_path: str):
        super().__init__(server, services)
        self.storage_path = storage_path

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self):
        # check if folder exists
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)

        return True

    async def on_close(self):
        return True

    # -------------------------------------------------------------- #
    # Recording File Management Methods
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
