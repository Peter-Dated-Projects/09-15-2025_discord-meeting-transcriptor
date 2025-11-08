"""
Presence Manager Service

This service manages the Discord bot's presence (status, activity, rich presence)
and tracks the number of active meetings.
"""

import asyncio
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from source.context import Context

from source.services.manager import ServicesManager


class PresenceManagerService:
    """
    Manages Discord bot presence and tracks active meeting count.

    Features:
    - Tracks active meeting count across all guilds
    - Updates bot presence on-demand when meetings start/stop
    - Displays "Playing Notetaker" status

    Note: py-cord does not support full rich presence features like details, state, or timestamps.
    Only basic activity status is supported.
    """

    def __init__(self, context: "Context"):
        self.context = context
        self.services: ServicesManager | None = None

        # Track active meetings count
        self._active_meetings_count: int = 0
        self._active_meetings_lock = asyncio.Lock()

    # -------------------------------------------------------------- #
    # Lifecycle Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services_manager: ServicesManager) -> None:
        """Initialize the Presence Manager Service."""
        self.services = services_manager

        await self.services.logging_service.info("Presence Manager Service started")

        # Initialize meeting count from active sessions
        if self.services.discord_recorder_service_manager:
            active_sessions = (
                self.services.discord_recorder_service_manager.get_all_active_sessions()
            )
            async with self._active_meetings_lock:
                self._active_meetings_count = len(active_sessions)
            await self.services.logging_service.info(
                f"Initialized meeting count to {self._active_meetings_count} from active sessions"
            )

    async def on_close(self) -> bool:
        """Stop the Presence Manager Service."""
        if self.services:
            await self.services.logging_service.info("Presence Manager Service stopped")

        return True

    # -------------------------------------------------------------- #
    # Meeting Tracking Methods
    # -------------------------------------------------------------- #

    async def get_meeting_count(self) -> int:
        """Get the current active meetings count."""
        async with self._active_meetings_lock:
            return self._active_meetings_count

    # -------------------------------------------------------------- #
    # Presence Update Methods
    # -------------------------------------------------------------- #

    async def _update_presence(self) -> None:
        """Update the bot's presence with current meeting count."""
        if not self.context.bot:
            return

        try:
            # Get current meeting count
            meeting_count = await self.get_meeting_count()

            # Get guild count
            guild_count = len(self.context.bot.guilds)

            # Create simple activity (py-cord doesn't support full rich presence)
            # This will show as "Playing Notetaker"
            activity = discord.Game(name="Notetaker")

            # Update presence
            await self.context.bot.change_presence(
                activity=activity,
                status=discord.Status.online,
            )

            if self.services:
                await self.services.logging_service.debug(
                    f"Updated presence: {meeting_count} meetings, {guild_count} guilds"
                )

        except Exception as e:
            if self.services:
                await self.services.logging_service.error(f"Failed to update presence: {e}")

    async def force_update_presence(self) -> None:
        """Force an immediate presence update (useful for initial setup)."""
        await self._update_presence()
