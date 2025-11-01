from source.server.server import ServerManager

# -------------------------------------------------------------- #
# Base Service Manager Class
# -------------------------------------------------------------- #


class Manager:
    """Base class for all manager services."""

    def __init__(self, server: ServerManager):
        self.server = server

        # check if server has been initialized
        if not self.server._initialized:
            raise RuntimeError(
                "ServerManager must be initialized before creating Manager instances."
            )

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self) -> None:
        """Actions to perform on manager start."""
        pass

    async def on_close(self) -> None:
        """Actions to perform on manager close."""
        pass


# -------------------------------------------------------------- #
# Services Manager Class
# -------------------------------------------------------------- #


class ServicesManager:
    """Manager for handling multiple service instances."""

    def __init__(
        self, server: ServerManager, file_service_manager: Manager, ffmpeg_service_manager: Manager
    ):
        self.server = server

        # add service managers as attributes
        self.file_service_manager = file_service_manager
        self.ffmpeg_service_manager = ffmpeg_service_manager

    async def initialize_all(self) -> None:
        """Initialize all service managers."""
        await self.file_service_manager.on_start()
        await self.ffmpeg_service_manager.on_start()
