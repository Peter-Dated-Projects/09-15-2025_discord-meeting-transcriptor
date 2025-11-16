import os
import platform
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from source.context import Context

from source.constructor import ServerManagerType
from source.services.logger import AsyncLoggingService
from source.services.manager import ServicesManager

# prefer a project-local .env.local file, then fallback to any .env
load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Constructor for Dynamic Creation of Services Manager
# -------------------------------------------------------------- #


def construct_services_manager(
    service_type: ServerManagerType,
    context: "Context",
    storage_path: str,
    recording_storage_path: str,
    transcription_storage_path: str,
    default_logging_path: str = "logs",
    log_file: str | None = None,
    use_timestamp_logs: bool = True,
):
    """Construct and return a service manager instance based on the service type.

    Args:
        service_type: Type of server manager (DEVELOPMENT or PRODUCTION)
        context: Context instance containing server and services
        storage_path: Path for general file storage
        recording_storage_path: Path for recording file storage
        transcription_storage_path: Path for transcription JSON file storage
        default_logging_path: Directory to store log files (default: "logs")
        log_file: Specific log file name (optional, overrides use_timestamp_logs)
        use_timestamp_logs: If True and log_file is None, creates timestamped log files (default: True)
    """

    file_service_manager = None
    recording_file_service_manager = None
    transcription_file_service_manager = None
    ffmpeg_service_manager = None
    sql_recording_service_manager = None
    sql_logging_service_manager = None
    discord_recorder_service_manager = None
    presence_manager_service = None
    transcription_job_manager = None

    # create logger
    logging_service = AsyncLoggingService(
        context=context,
        log_dir=default_logging_path,
        log_file=log_file,
        use_timestamp=use_timestamp_logs,
    )

    # create file service manager
    if (
        service_type == ServerManagerType.DEVELOPMENT
        or service_type == ServerManagerType.PRODUCTION
    ):

        # -------------------------------------------------------------- #
        # Service Managers Setup
        # -------------------------------------------------------------- #

        from source.services.ffmpeg_manager.manager import FFmpegManagerService
        from source.services.file_manager.manager import FileManagerService
        from source.services.recording_file_manager.manager import (
            RecordingFileManagerService,
        )
        from source.services.transcription_file_manager.manager import (
            TranscriptionFileManagerService,
        )

        file_service_manager = FileManagerService(context=context, storage_path=storage_path)
        recording_file_service_manager = RecordingFileManagerService(
            context=context, recording_storage_path=recording_storage_path
        )
        transcription_file_service_manager = TranscriptionFileManagerService(
            context=context, transcription_storage_path=transcription_storage_path
        )

        # Decide ffmpeg binary path based on environment and platform
        if platform.system().lower().startswith("win") or os.name == "nt":
            ffmpeg_env = os.getenv("WINDOWS_FFMPEG_PATH")
        else:
            ffmpeg_env = os.getenv("MAC_FFMPEG_PATH")

        ffmpeg_path = ffmpeg_env

        ffmpeg_service_manager = FFmpegManagerService(context=context, ffmpeg_path=ffmpeg_path)

        # -------------------------------------------------------------- #
        # DB Interfaces Setup
        # -------------------------------------------------------------- #

        from source.services.recording_sql_manager.manager import SQLRecordingManagerService
        from source.services.sql_logging.manager import SQLLoggingManagerService

        sql_recording_service_manager = SQLRecordingManagerService(context=context)
        sql_logging_service_manager = SQLLoggingManagerService(context=context)

        # -------------------------------------------------------------- #
        # Discord Recorder Setup
        # -------------------------------------------------------------- #

        from source.services.discord_recorder.manager import DiscordRecorderManagerService

        discord_recorder_service_manager = DiscordRecorderManagerService(context=context)

        # -------------------------------------------------------------- #
        # Presence Manager Setup
        # -------------------------------------------------------------- #

        from source.services.presence_manager.manager import PresenceManagerService

        presence_manager_service = PresenceManagerService(context=context)

        # -------------------------------------------------------------- #
        # Transcription Job Manager Setup
        # -------------------------------------------------------------- #

        from source.services.transcription_job_manager.manager import (
            TranscriptionJobManagerService,
        )

        transcription_job_manager = TranscriptionJobManagerService(context=context)

    # TODO: https://www.notion.so/DISC-19-create-ffmpeg-service-29c5eca3b9df805a949fdcd5850eaf5a?source=copy_link
    # # create ffmpeg service manager
    # if service_type == ServerManagerType.DEVELOPMENT:
    #     from source.services.ffmpeg.manager import FFmpegService
    #     ffmpeg_service_manager = FFmpegService()

    if (
        not file_service_manager or not sql_recording_service_manager
    ):  # or not ffmpeg_service_manager:
        raise ValueError(f"Unsupported service type: {service_type}")

    return ServicesManager(
        context=context,
        file_service_manager=file_service_manager,
        recording_file_service_manager=recording_file_service_manager,
        transcription_file_service_manager=transcription_file_service_manager,
        ffmpeg_service_manager=ffmpeg_service_manager,
        logging_service=logging_service,
        sql_recording_service_manager=sql_recording_service_manager,
        sql_logging_service_manager=sql_logging_service_manager,
        discord_recorder_service_manager=discord_recorder_service_manager,
        presence_manager_service=presence_manager_service,
        transcription_job_manager=transcription_job_manager,
    )
