import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import discord

    from source.server.server import ServerManager
    from source.services.manager import ServicesManager

# -------------------------------------------------------------- #
# Context Class
# -------------------------------------------------------------- #


class Context:
    """
    Central context object that provides access to all server components,
    services, and the Discord bot instance.

    This allows all services and server managers to access each other and the bot
    without circular dependencies or passing multiple objects individually.
    """

    def __init__(self):
        self.server_manager: ServerManager | None = None
        self.services_manager: ServicesManager | None = None
        self.bot: discord.Bot | None = None
        self._shutting_down: bool = False
        self._shutdown_event: asyncio.Event = asyncio.Event()

    def set_server_manager(self, server_manager: "ServerManager") -> None:
        """Set the server manager instance."""
        self.server_manager = server_manager

    def set_services_manager(self, services_manager: "ServicesManager") -> None:
        """Set the services manager instance."""
        self.services_manager = services_manager

    def set_bot(self, bot: "discord.Bot") -> None:
        """Set the Discord bot instance."""
        self.bot = bot

    def is_shutting_down(self) -> bool:
        """Check if the application is shutting down."""
        return self._shutting_down

    def mark_shutdown_started(self) -> None:
        """Mark that shutdown has been initiated."""
        self._shutting_down = True
        self._shutdown_event.set()

    def wait_for_shutdown(self) -> asyncio.Event:
        """Get the shutdown event for services to monitor."""
        return self._shutdown_event
