from source.server.server import ServerManager

# -------------------------------------------------------------- #
# Base Manager Class
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

    def on_start(self) -> None:
        """Actions to perform on manager start."""
        pass

    def on_close(self) -> None:
        """Actions to perform on manager close."""
        pass
