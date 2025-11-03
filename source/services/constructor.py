from source.constructor import ServerManagerType
from source.server.server import ServerManager
from source.services.logger import AsyncLoggingService
from source.services.manager import ServicesManager

import os
import platform

from dotenv import load_dotenv

# prefer a project-local .env.local file, then fallback to any .env
load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Constructor for Dynamic Creation of Services Manager
# -------------------------------------------------------------- #


def construct_services_manager(
    service_type: ServerManagerType,
    server: ServerManager,
    storage_path: str,
    recording_storage_path: str,
    default_logging_path: str = "logs",
    default_log_file: str = "app.log",
):
    """Construct and return a service manager instance based on the service type."""

    file_service_manager = None
    recording_file_service_manager = None
    transcription_file_service_manager = None
    ffmpeg_service_manager = None
    sql_recording_service_manager = None

    # create logger
    logging_service = AsyncLoggingService(
        server=server, log_dir=default_logging_path, log_file=default_log_file
    )

    # create file service manager
    if (
        service_type == ServerManagerType.DEVELOPMENT
        or service_type == ServerManagerType.PRODUCTION
    ):

        # -------------------------------------------------------------- #
        # Service Managers Setup
        # -------------------------------------------------------------- #

        from source.services.file_manager.manager import FileManagerService
        from source.services.recording_file_manager.manager import (
            RecordingFileManagerService,
        )
        from source.services.ffmpeg_manager.manager import FFmpegManagerService

        file_service_manager = FileManagerService(server=server, storage_path=storage_path)
        recording_file_service_manager = RecordingFileManagerService(
            server=server, recording_storage_path=recording_storage_path
        )

        # Decide ffmpeg binary path based on environment and platform
        if platform.system().lower().startswith("win") or os.name == "nt":
            ffmpeg_env = os.getenv("WINDOWS_FFMPEG_PATH")
        else:
            ffmpeg_env = os.getenv("MAC_FFMPEG_PATH")

        ffmpeg_path = ffmpeg_env

        ffmpeg_service_manager = FFmpegManagerService(server=server, ffmpeg_path=ffmpeg_path)

        # -------------------------------------------------------------- #
        # DB Interfaces Setup
        # -------------------------------------------------------------- #

        from source.services.recording_sql.manager import SQLRecordingManagerService

        sql_recording_service_manager = SQLRecordingManagerService(server=server)

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
        server=server,
        file_service_manager=file_service_manager,
        recording_file_service_manager=recording_file_service_manager,
        transcription_file_service_manager=transcription_file_service_manager,
        ffmpeg_service_manager=ffmpeg_service_manager,
        logging_service=logging_service,
        sql_recording_service_manager=sql_recording_service_manager,
    )
