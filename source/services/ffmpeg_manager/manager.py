from source.server.server import ServerManager

from source.services.manager import BaseFFmpegServiceManager

# -------------------------------------------------------------- #
# FFmpeg Manager Service
# -------------------------------------------------------------- #


class FFmpegHandler:
    def __init__(self, ffmpeg_path: str):
        self.ffmpeg_path = ffmpeg_path


class FFmpegManagerService(BaseFFmpegServiceManager):
    """Service for managing FFmpeg operations."""

    def __init__(self, server: ServerManager, ffmpeg_path: str):
        super().__init__(server)

        self.ffmpeg_path = ffmpeg_path
        self.handler = FFmpegHandler(ffmpeg_path)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("FFmpegManagerService initialized")
        return True

    async def on_close(self):
        return True

    # -------------------------------------------------------------- #
    # FFmpeg Management Methods
    # -------------------------------------------------------------- #
