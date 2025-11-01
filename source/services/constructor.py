from source.constructor import ServerManagerType
from source.server.server import ServerManager
from source.services.manager import ServicesManager

# -------------------------------------------------------------- #
# Constructor for Dynamic Creation of Services Manager
# -------------------------------------------------------------- #


def construct_services_manager(
    service_type: ServerManagerType, server: ServerManager, storage_path: str
):
    """Construct and return a service manager instance based on the service type."""

    file_service_manager = None
    recording_file_service_manager = None
    transcription_file_service_manager = None
    ffmpeg_service_manager = None

    # create file service manager
    if (
        service_type == ServerManagerType.DEVELOPMENT
        or service_type == ServerManagerType.PRODUCTION
    ):
        from source.services.file_manager.manager import FileManagerService
        from source.services.recording_file_manager.manager import (
            RecordingFileManagerService,
        )

        file_service_manager = FileManagerService(server=server, storage_path=storage_path)
        recording_file_service_manager = RecordingFileManagerService(server=server)

    # TODO: https://www.notion.so/DISC-19-create-ffmpeg-service-29c5eca3b9df805a949fdcd5850eaf5a?source=copy_link
    # # create ffmpeg service manager
    # if service_type == ServerManagerType.DEVELOPMENT:
    #     from source.services.ffmpeg.manager import FFmpegService
    #     ffmpeg_service_manager = FFmpegService()

    if not file_service_manager:  # or not ffmpeg_service_manager:
        raise ValueError(f"Unsupported service type: {service_type}")

    return ServicesManager(
        server=server,
        file_service_manager=file_service_manager,
        recording_file_service_manager=recording_file_service_manager,
        transcription_file_service_manager=transcription_file_service_manager,
        ffmpeg_service_manager=ffmpeg_service_manager,
    )
