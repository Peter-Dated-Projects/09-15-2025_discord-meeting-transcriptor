from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from source.context import Context


# -------------------------------------------------------------- #
# Services Manager Class
# -------------------------------------------------------------- #


class ServicesManager:
    """Manager for handling multiple service instances."""

    def __init__(
        self,
        context: Context,
        logging_service: BaseAsyncLoggingService,
        file_service_manager: BaseFileServiceManager,
        recording_file_service_manager: BaseRecordingFileServiceManager,
        transcription_file_service_manager: BaseTranscriptionFileServiceManager,
        ffmpeg_service_manager: BaseFFmpegServiceManager,
        sql_recording_service_manager: BaseSQLRecordingServiceManager,
        discord_recorder_service_manager: BaseDiscordRecorderServiceManager | None = None,
    ):
        self.context = context
        # Backward compatibility - keep server reference
        self.server = context.server_manager

        self.logging_service = logging_service

        # add service managers as attributes
        self.file_service_manager = file_service_manager
        self.recording_file_service_manager = recording_file_service_manager
        self.transcription_file_service_manager = transcription_file_service_manager
        self.ffmpeg_service_manager = ffmpeg_service_manager

        # DB interfaces
        self.sql_recording_service_manager = sql_recording_service_manager

        # Discord recorder
        self.discord_recorder_service_manager = discord_recorder_service_manager

    async def initialize_all(self) -> None:
        """Initialize all service managers."""

        # Logging
        await self.logging_service.on_start(self)

        # Services managers
        await self.file_service_manager.on_start(self)
        await self.recording_file_service_manager.on_start(self)
        await self.ffmpeg_service_manager.on_start(self)

        # DB interfaces
        await self.sql_recording_service_manager.on_start(self)

        # Discord recorder
        await self.discord_recorder_service_manager.on_start(self)

        # TODO - need to create
        # await self.transcription_file_service_manager.on_start(self)


# -------------------------------------------------------------- #
# Base Service Manager Class
# -------------------------------------------------------------- #


class Manager(ABC):
    """Base class for all manager services."""

    def __init__(self, context: Context):
        self.context = context
        # Backward compatibility - keep server reference
        self.server = context.server_manager
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

    def __init__(self, context):
        super().__init__(context)

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

    @abstractmethod
    async def create_file(self, filename: str) -> None:
        """Create an empty file."""
        pass

    @abstractmethod
    async def ensure_parent_dir(self, filepath: str) -> None:
        """Ensure the parent directory of the given filepath exists."""
        pass

    @abstractmethod
    async def _acquire_file_lock_oneshot(self, filename: str):
        """Asynchronous context manager to acquire a file lock for atomic operations."""
        pass

    @abstractmethod
    async def _release_file_lock_oneshot(self, filename: str):
        """Asynchronous context manager to release a file lock."""
        pass


class BaseRecordingFileServiceManager(Manager):
    """Specialized manager for recording file services."""

    def __init__(self, context):
        super().__init__(context)

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

    def __init__(self, context):
        super().__init__(context)

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

    def __init__(self, context):
        super().__init__(context)


class BaseSQLRecordingServiceManager(Manager):
    """Specialized manager for SQL recording services (temp and persistent)."""

    def __init__(self, context):
        super().__init__(context)

    @abstractmethod
    async def insert_temp_recording(
        self, meeting_id: str, user_id: str, guild_id: str, pcm_path: str, created_at=None
    ) -> str:
        """Insert a new temp recording chunk."""
        pass

    @abstractmethod
    async def update_temp_recording_transcode_started(self, temp_recording_id: str) -> None:
        """Update temp recording when transcode starts."""
        pass

    @abstractmethod
    async def update_temp_recording_transcode_completed(
        self, temp_recording_id: str, mp3_path: str, sha256: str | None, duration_ms: int | None
    ) -> None:
        """Update temp recording when transcode completes."""
        pass

    @abstractmethod
    async def update_temp_recording_transcode_failed(self, temp_recording_id: str) -> None:
        """Update temp recording when transcode fails."""
        pass

    @abstractmethod
    async def mark_temp_recording_cleaned(self, temp_recording_id: str) -> None:
        """Mark temp recording as cleaned (PCM deleted)."""
        pass

    @abstractmethod
    async def get_temp_recordings_for_meeting(
        self, meeting_id: str, status_filter=None
    ) -> list[dict]:
        """Get all temp recordings for a meeting."""
        pass

    @abstractmethod
    async def promote_temp_recordings_to_persistent(
        self, meeting_id: str, user_id: str | None = None
    ) -> str | None:
        """Promote temp recordings to persistent storage."""
        pass


class BaseFFmpegServiceManager(Manager):
    """Specialized manager for FFmpeg services."""

    def __init__(self, context):
        super().__init__(context)

    @abstractmethod
    def get_ffmpeg_path(self) -> str:
        """Get the FFmpeg executable path."""
        pass

    @abstractmethod
    async def create_pcm_to_mp3_stream_handler(self) -> Any:
        """Create a PCM to MP3 stream handler."""
        pass

    @abstractmethod
    async def queue_mp3_to_whisper_format_job(
        self, input_path: str, output_path: str, options: dict
    ) -> bool:
        """
        Convert an MP3 file to Whisper-compatible format.

        Args:
            input_path: Path to the input MP3 file
            output_path: Path to the output file
            options: Dictionary of FFmpeg options

        Returns:
            True if conversion was successful, False otherwise
        """
        pass


class BaseTranscriptionFileServiceManager(Manager):
    """Specialized manager for transcription file services."""

    def __init__(self, context):
        super().__init__(context)


class BaseDiscordRecorderServiceManager(Manager):
    """Specialized manager for Discord recorder services."""

    def __init__(self, context):
        super().__init__(context)

    @abstractmethod
    async def start_session(
        self,
        discord_voice_client: Any,  # discord.VoiceClient
        channel_id: int,
        meeting_id: str | None = None,
        user_id: str | None = None,
        guild_id: str | None = None,
    ) -> bool:
        """Start a new recording session."""
        pass

    @abstractmethod
    async def stop_session(self, channel_id: int) -> bool:
        """Stop a recording session."""
        pass

    @abstractmethod
    async def pause_session(self, channel_id: int) -> bool:
        """Pause a recording session."""
        pass

    @abstractmethod
    async def resume_session(self, channel_id: int) -> bool:
        """Resume a paused recording session."""
        pass
