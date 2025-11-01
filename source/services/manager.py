from __future__ import annotations

from abc import ABC, abstractmethod

from source.server.server import ServerManager

# -------------------------------------------------------------- #
# Services Manager Class
# -------------------------------------------------------------- #


class ServicesManager:
    """Manager for handling multiple service instances."""

    def __init__(
        self,
        server: ServerManager,
        file_service_manager: BaseFileServiceManager,
        recording_file_service_manager: BaseRecordingFileServiceManager,
        transcription_file_service_manager: BaseTranscriptionFileServiceManager,
        ffmpeg_service_manager: BaseFFmpegServiceManager,
        logging_service: BaseAsyncLoggingService,
    ):
        self.server = server

        # add service managers as attributes
        self.file_service_manager = file_service_manager
        self.recording_file_service_manager = recording_file_service_manager
        self.transcription_file_service_manager = transcription_file_service_manager
        self.ffmpeg_service_manager = ffmpeg_service_manager
        self.logging_service = logging_service

    async def initialize_all(self) -> None:
        """Initialize all service managers."""
        await self.file_service_manager.on_start(self)
        await self.recording_file_service_manager.on_start(self)
        await self.logging_service.on_start(self)
        # await self.transcription_file_service_manager.on_start(self)
        # await self.ffmpeg_service_manager.on_start(self)


# -------------------------------------------------------------- #
# Base Service Manager Class
# -------------------------------------------------------------- #


class Manager(ABC):
    """Base class for all manager services."""

    def __init__(self, server: ServerManager):
        self.server = server
        self.services = None

        # check if server has been initialized
        if not self.server._initialized:
            raise RuntimeError(
                "ServerManager must be initialized before creating Manager instances."
            )

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services: ServicesManager) -> None:
        """Actions to perform on manager start."""
        self.services = services

    async def on_close(self) -> None:
        """Actions to perform on manager close."""
        pass


# -------------------------------------------------------------- #
# Specialized Manager Classes
# -------------------------------------------------------------- #


class BaseFileServiceManager(Manager):
    """Specialized manager for file services."""

    def __init__(self, server):
        super().__init__(server)

    @abstractmethod
    def get_storage_path(self) -> str:
        """Get the storage path."""
        pass

    @abstractmethod
    def get_storage_absolute_path(self) -> str:
        """Get the absolute storage path."""
        pass

    @abstractmethod
    async def save_file(self, filename: str, data: bytes) -> str:
        """Save data to a file."""
        pass

    @abstractmethod
    async def read_file(self, filename: str) -> bytes:
        """Read data from a file."""
        pass

    @abstractmethod
    async def delete_file(self, filename: str) -> None:
        """Delete a file."""
        pass

    @abstractmethod
    async def update_file(self, filename: str, data: bytes) -> None:
        """Update a file."""
        pass

    @abstractmethod
    async def get_folder_contents(self, folder_path: str) -> list[str]:
        """Get the contents of a folder."""
        pass

    @abstractmethod
    async def file_exists(self, filename: str) -> bool:
        """Check if a file exists."""
        pass


class BaseRecordingFileServiceManager(Manager):
    """Specialized manager for recording file services."""

    def __init__(self, server):
        super().__init__(server)

    @abstractmethod
    def get_persistent_storage_path(self) -> str:
        """Get the absolute storage path."""
        pass

    @abstractmethod
    def get_temporary_storage_path(self) -> str:
        """Get the absolute temporary storage path."""
        pass

    @abstractmethod
    async def save_to_temp_file(self, filename: str, data: bytes) -> str:
        """Save data to a temporary file."""
        pass

    @abstractmethod
    async def move_temp_to_persistent(self, filename: str) -> str:
        """Move a file from temporary to persistent storage."""
        pass

    @abstractmethod
    async def delete_persistent_file(self, filename: str) -> None:
        """Delete a file from persistent storage."""
        pass

    @abstractmethod
    async def delete_temp_file(self, filename: str) -> None:
        """Delete a file from temporary storage."""
        pass

    @abstractmethod
    def get_filename_from_persistent_path(self, persistent_path: str) -> str:
        """Get the filename from a persistent storage path."""
        pass

    @abstractmethod
    def get_filename_from_temporary_path(self, temporary_path: str) -> str:
        """Get the filename from a temporary storage path."""
        pass


class BaseAsyncLoggingService(Manager):
    """Specialized manager for asynchronous logging services."""

    def __init__(self, server):
        super().__init__(server)

    @abstractmethod
    async def log(self, message: str) -> None:
        """Log a message asynchronously."""
        pass

    @abstractmethod
    async def debug(self, message: str) -> None:
        """Log an error message asynchronously."""
        pass

    @abstractmethod
    async def info(self, message: str) -> None:
        """Log an info message asynchronously."""
        pass

    @abstractmethod
    async def warning(self, message: str) -> None:
        """Log a warning message asynchronously."""
        pass

    @abstractmethod
    async def error(self, message: str) -> None:
        """Log an error message asynchronously."""
        pass

    @abstractmethod
    async def critical(self, message: str) -> None:
        """Log a critical message asynchronously."""
        pass


class BaseSQLLoggingServiceManager(Manager):
    """Specialized manager for SQL logging services."""

    def __init__(self, server):
        super().__init__(server)


class BaseFFmpegServiceManager(Manager):
    """Specialized manager for FFmpeg services."""

    def __init__(self, server):
        super().__init__(server)


class BaseTranscriptionFileServiceManager(Manager):
    """Specialized manager for transcription file services."""

    def __init__(self, server):
        super().__init__(server)
