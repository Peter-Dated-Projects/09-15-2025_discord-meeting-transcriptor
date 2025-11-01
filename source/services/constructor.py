import os

from source.constructor import ServerManagerType
from source.services.manager import ServicesManager

# -------------------------------------------------------------- #
# Constructor for Dynamic Creation of Services Manager
# -------------------------------------------------------------- #


def construct_service_manager(service_type: ServerManagerType, storage_path: str):
    """Construct and return a service manager instance based on the service type."""

    file_service_manager = None
    ffmpeg_service_manager = None

    # create file service manager
    if (
        service_type == ServerManagerType.DEVELOPMENT
        or service_type == ServerManagerType.PRODUCTION
    ):
        from source.services.file_manager.manager import FileManagerService

        file_service_manager = FileManagerService(storage_path=storage_path)

    # TODO: https://www.notion.so/DISC-19-create-ffmpeg-service-29c5eca3b9df805a949fdcd5850eaf5a?source=copy_link
    # # create ffmpeg service manager
    # if service_type == ServerManagerType.DEVELOPMENT:
    #     from source.services.ffmpeg.manager import FFmpegService
    #     ffmpeg_service_manager = FFmpegService()

    if not file_service_manager or not ffmpeg_service_manager:
        raise ValueError(f"Unsupported service type: {service_type}")

    return ServicesManager(
        file_service_manager=file_service_manager,
        ffmpeg_service_manager=ffmpeg_service_manager,
    )
