from __future__ import annotations

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

    async def on_start(self):
        # check if folder exists
        if not os.path.exists(self.recording_storage_path):
            os.makedirs(self.recording_storage_path)
        if not os.path.exists(self.temp_path):
            os.makedirs(self.temp_path)
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)

        return True

    async def on_close(self):
        # delete all items in temp folder
        for filename in os.listdir(self.temp_path):
            file_path = os.path.join(self.temp_path, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    os.rmdir(file_path)
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
        return os.path.join(self.temp_path, filename)

    async def move_temp_to_persistent(self, filename: str) -> str:
        """Move a file from temporary to persistent storage."""
        temp_file_path = os.path.join(self.temp_path, filename)
        persistent_file_path = os.path.join(self.storage_path, filename)

        os.rename(temp_file_path, persistent_file_path)
        return persistent_file_path

    async def delete_persistent_file(self, filename: str) -> None:
        """Delete a file from persistent storage."""
        persistent_file_path = os.path.join(self.storage_path, filename)
        await self.services.file_service_manager.delete_file(persistent_file_path)

    async def delete_temp_file(self, filename: str) -> None:
        """Delete a file from temporary storage."""
        temp_file_path = os.path.join(self.temp_path, filename)
        await self.services.file_service_manager.delete_file(temp_file_path)
