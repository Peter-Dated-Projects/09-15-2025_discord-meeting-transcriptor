from __future__ import annotations

import asyncio
import os

from source.server.server import ServerManager
from source.services.manager import BaseRecordingFileServiceManager

# -------------------------------------------------------------- #
# Recording File Manager Service
# -------------------------------------------------------------- #


class RecordingFileManagerService(BaseRecordingFileServiceManager):
    """Service for managing recording files."""

    def __init__(self, server: ServerManager, recording_storage_path: str):
        super().__init__(server)
        self.recording_storage_path = recording_storage_path

        self.temp_path = os.path.join(self.recording_storage_path, "temp")
        self.storage_path = os.path.join(self.recording_storage_path, "storage")

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)

        # Run blocking filesystem operations in executor
        loop = asyncio.get_event_loop()

        # check if folder exists
        if not await loop.run_in_executor(None, os.path.exists, self.recording_storage_path):
            await loop.run_in_executor(None, os.makedirs, self.recording_storage_path)
        if not await loop.run_in_executor(None, os.path.exists, self.temp_path):
            await loop.run_in_executor(None, os.makedirs, self.temp_path)
        if not await loop.run_in_executor(None, os.path.exists, self.storage_path):
            await loop.run_in_executor(None, os.makedirs, self.storage_path)

        await self.services.logging_service.info(
            f"RecordingFileManagerService initialized with storage path: {self.recording_storage_path}"
        )
        return True

    async def on_close(self):
        # delete all items in temp folder (non-blocking)
        loop = asyncio.get_event_loop()
        filenames = await loop.run_in_executor(None, os.listdir, self.temp_path)

        for filename in filenames:
            file_path = os.path.join(self.temp_path, filename)
            try:
                # Check file type in executor
                is_file = await loop.run_in_executor(None, os.path.isfile, file_path)
                is_link = await loop.run_in_executor(None, os.path.islink, file_path)
                is_dir = await loop.run_in_executor(None, os.path.isdir, file_path)

                if is_file or is_link:
                    await loop.run_in_executor(None, os.unlink, file_path)
                elif is_dir:
                    await loop.run_in_executor(None, os.rmdir, file_path)
            except Exception as e:
                self.logger.error(f"Failed to delete {file_path}. Reason: {e}")
        return True

    # -------------------------------------------------------------- #
    # Recording File Management Methods
    # -------------------------------------------------------------- #

    def get_persistent_storage_path(self) -> str:
        """Get the absolute storage path."""
        return os.path.abspath(self.storage_path)

    def get_temporary_storage_path(self) -> str:
        """Get the absolute temporary storage path."""
        return os.path.abspath(self.temp_path)

    def get_filename_from_persistent_path(self, persistent_path: str) -> str:
        """Get the filename from a persistent storage path."""
        return os.path.basename(persistent_path)

    def get_filename_from_temporary_path(self, temporary_path: str) -> str:
        """Get the filename from a temporary storage path."""
        return os.path.basename(temporary_path)

    async def save_to_temp_file(self, filename: str, data: bytes) -> str:
        """Save data to a temporary file."""
        await self.services.file_service_manager.save_file(filename, data)
        temp_path = os.path.join(self.temp_path, filename)
        await self.services.logging_service.info(
            f"Saved recording to temp file: {filename} ({len(data)} bytes)"
        )
        return temp_path

    async def move_temp_to_persistent(self, filename: str) -> str:
        """Move a file from temporary to persistent storage."""
        temp_file_path = os.path.join(self.temp_path, filename)
        persistent_file_path = os.path.join(self.storage_path, filename)

        # Use executor for blocking os.rename
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, os.rename, temp_file_path, persistent_file_path)

        await self.services.logging_service.info(
            f"Moved recording file to persistent storage: {filename}"
        )
        return persistent_file_path

    async def delete_persistent_file(self, filename: str) -> None:
        """Delete a file from persistent storage."""
        persistent_file_path = os.path.join(self.storage_path, filename)
        await self.services.file_service_manager.delete_file(persistent_file_path)
        await self.services.logging_service.info(f"Deleted persistent recording file: {filename}")

    async def delete_temp_file(self, filename: str) -> None:
        """Delete a file from temporary storage."""
        temp_file_path = os.path.join(self.temp_path, filename)
        await self.services.file_service_manager.delete_file(temp_file_path)
        await self.services.logging_service.info(f"Deleted temporary recording file: {filename}")
