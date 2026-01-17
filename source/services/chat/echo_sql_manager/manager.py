from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import EchoChannelsModel
from source.services.manager import Manager
from source.utils import get_current_timestamp_est

# -------------------------------------------------------------- #
# Echo SQL Manager Service
# -------------------------------------------------------------- #


class EchoSQLManagerService(Manager):
    """Service for managing echo channel SQL operations.

    This service handles persistence of echo-enabled channels to the database.
    Echo channels allow bot interaction without creating threads.
    """

    def __init__(self, context: "Context"):
        super().__init__(context)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("EchoSQLManagerService initialized")
        return True

    async def on_close(self):
        await self.services.logging_service.info("EchoSQLManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Echo Channel CRUD Methods
    # -------------------------------------------------------------- #

    async def enable_echo_channel(self, channel_id: str, guild_id: str) -> bool:
        """
        Enable echo for a channel by inserting it into the database.

        Args:
            channel_id: Discord Channel ID
            guild_id: Discord Guild (Server) ID

        Returns:
            True if successfully enabled, False if already exists

        Raises:
            ValueError: If any required field is invalid
        """
        # Validate inputs
        if not channel_id or len(channel_id) < 16:
            raise ValueError("channel_id must be at least 16 characters long")
        if not guild_id or len(guild_id) < 17:
            raise ValueError("guild_id must be at least 17 characters long")

        # Check if already enabled
        existing = await self.is_echo_enabled(channel_id)
        if existing:
            await self.services.logging_service.debug(
                f"Echo already enabled for channel {channel_id}"
            )
            return False

        # Prepare data
        timestamp = get_current_timestamp_est()
        echo_data = {
            "channel_id": channel_id,
            "guild_id": guild_id,
            "enabled_at": timestamp,
        }

        # Build and execute insert statement
        stmt = insert(EchoChannelsModel).values(**echo_data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Enabled echo for channel {channel_id} in guild {guild_id}"
        )

        return True

    async def disable_echo_channel(self, channel_id: str) -> bool:
        """
        Disable echo for a channel by removing it from the database.

        Args:
            channel_id: Discord Channel ID

        Returns:
            True if successfully disabled, False if not found

        Raises:
            ValueError: If channel_id is invalid
        """
        # Validate input
        if not channel_id or len(channel_id) < 16:
            raise ValueError("channel_id must be at least 16 characters long")

        # Check if exists
        existing = await self.is_echo_enabled(channel_id)
        if not existing:
            await self.services.logging_service.debug(
                f"Echo not enabled for channel {channel_id}, nothing to disable"
            )
            return False

        # Build and execute delete statement
        stmt = delete(EchoChannelsModel).where(EchoChannelsModel.channel_id == channel_id)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(f"Disabled echo for channel {channel_id}")

        return True

    async def is_echo_enabled(self, channel_id: str) -> bool:
        """
        Check if echo is enabled for a channel.

        Args:
            channel_id: Discord Channel ID

        Returns:
            True if echo is enabled, False otherwise
        """
        if not channel_id:
            return False

        # Build select query
        query = select(EchoChannelsModel).where(EchoChannelsModel.channel_id == channel_id)

        # Execute query
        results = await self.server.sql_client.execute(query)

        return bool(results)

    async def get_all_enabled_channel_ids(self) -> list[str]:
        """
        Retrieve all channel IDs that have echo enabled.

        Returns:
            List of Discord channel IDs with echo enabled
        """
        # Build select query for just the channel_id column
        query = select(EchoChannelsModel.channel_id)

        # Execute query
        results = await self.server.sql_client.execute(query)

        # Extract channel IDs from results
        channel_ids = []
        if results:
            for row in results:
                if isinstance(row, dict):
                    channel_ids.append(row.get("channel_id"))
                else:
                    # If it's a Row object with attributes
                    channel_ids.append(
                        row.channel_id if hasattr(row, "channel_id") else str(row[0])
                    )

        await self.services.logging_service.debug(
            f"Retrieved {len(channel_ids)} echo-enabled channels from database"
        )
        return channel_ids

    async def get_echo_channels_by_guild(self, guild_id: str) -> list[dict]:
        """
        Retrieve all echo-enabled channels for a specific guild.

        Args:
            guild_id: Discord Guild (Server) ID

        Returns:
            List of echo channel dictionaries

        Raises:
            ValueError: If guild_id is invalid
        """
        # Validate input
        if not guild_id or len(guild_id) < 17:
            raise ValueError("guild_id must be at least 17 characters long")

        # Build select query
        query = select(EchoChannelsModel).where(EchoChannelsModel.guild_id == guild_id)

        # Execute query
        results = await self.server.sql_client.execute(query)

        await self.services.logging_service.debug(
            f"Found {len(results) if results else 0} echo channels for guild {guild_id}"
        )
        return results if isinstance(results, list) else []

    async def delete_echo_channels_by_guild(self, guild_id: str) -> int:
        """
        Delete all echo-enabled channels for a specific guild.
        Useful when bot leaves a guild.

        Args:
            guild_id: Discord Guild (Server) ID

        Returns:
            Number of channels deleted

        Raises:
            ValueError: If guild_id is invalid
        """
        # Validate input
        if not guild_id or len(guild_id) < 17:
            raise ValueError("guild_id must be at least 17 characters long")

        # First count how many will be deleted
        channels = await self.get_echo_channels_by_guild(guild_id)
        count = len(channels)

        # Build and execute delete statement
        stmt = delete(EchoChannelsModel).where(EchoChannelsModel.guild_id == guild_id)
        await self.server.sql_client.execute(stmt)

        await self.services.logging_service.info(
            f"Deleted {count} echo channels for guild {guild_id}"
        )
        return count
