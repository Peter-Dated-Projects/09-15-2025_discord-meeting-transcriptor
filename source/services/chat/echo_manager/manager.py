import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.echo_sql_manager import EchoSQLManagerService

from source.services.manager import Manager

# -------------------------------------------------------------- #
# Echo Manager - In-Memory Cache
# -------------------------------------------------------------- #


class EchoManager(Manager):
    """In-memory manager for echo-enabled channels.

    This manager maintains a set of channel IDs where echo bot interaction is enabled.
    Context is stored per-channel and persists across messages while echo is enabled.
    When echo is disabled, context is cleared.

    Key behaviors:
    - Channels (not threads) can have echo enabled/disabled
    - Context persists per-channel while enabled
    - Disabling clears context (messages during disabled period are not remembered)
    - State persists to database for cross-session persistence
    """

    def __init__(self, context: "Context"):
        super().__init__(context)
        # Set of channel IDs with echo enabled
        self.enabled_channels: set[str] = set()
        # Context storage: channel_id -> list of message dicts
        # Each message dict: {"role": "user"|"assistant", "content": str, "user_id": str|None}
        self.channel_contexts: dict[str, list[dict[str, Any]]] = {}

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("EchoManager initialized")
        return True

    async def on_close(self):
        await self.services.logging_service.info("EchoManager closed")
        # Clear in-memory state
        self.enabled_channels.clear()
        self.channel_contexts.clear()
        return True

    # -------------------------------------------------------------- #
    # Echo Enable/Disable Methods
    # -------------------------------------------------------------- #

    async def enable_echo(
        self, channel_id: str, guild_id: str, echo_sql_manager: "EchoSQLManagerService"
    ) -> bool:
        """Enable echo for a channel.

        Args:
            channel_id: Discord Channel ID
            guild_id: Discord Guild ID
            echo_sql_manager: SQL manager for persistence

        Returns:
            True if successfully enabled, False if already enabled
        """
        if channel_id in self.enabled_channels:
            return False

        # Add to in-memory set
        self.enabled_channels.add(channel_id)
        # Initialize empty context
        self.channel_contexts[channel_id] = []

        # Persist to database
        try:
            await echo_sql_manager.enable_echo_channel(channel_id, guild_id)
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to persist echo enable for channel {channel_id}: {e}"
            )
            # Still keep in memory even if DB fails

        await self.services.logging_service.info(f"Echo enabled for channel {channel_id}")
        return True

    async def disable_echo(
        self, channel_id: str, echo_sql_manager: "EchoSQLManagerService"
    ) -> bool:
        """Disable echo for a channel and clear its context.

        Args:
            channel_id: Discord Channel ID
            echo_sql_manager: SQL manager for persistence

        Returns:
            True if successfully disabled, False if not enabled
        """
        if channel_id not in self.enabled_channels:
            return False

        # Remove from in-memory set
        self.enabled_channels.discard(channel_id)
        # Clear context (messages during disabled period won't be remembered)
        self.channel_contexts.pop(channel_id, None)

        # Persist to database
        try:
            await echo_sql_manager.disable_echo_channel(channel_id)
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to persist echo disable for channel {channel_id}: {e}"
            )
            # Still keep disabled in memory even if DB fails

        await self.services.logging_service.info(
            f"Echo disabled for channel {channel_id}, context cleared"
        )
        return True

    def is_echo_enabled(self, channel_id: str) -> bool:
        """Check if echo is enabled for a channel.

        Args:
            channel_id: Discord Channel ID

        Returns:
            True if echo is enabled, False otherwise
        """
        return channel_id in self.enabled_channels

    # -------------------------------------------------------------- #
    # Context Management Methods
    # -------------------------------------------------------------- #

    def add_message_to_context(
        self,
        channel_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
    ) -> bool:
        """Add a message to the channel's context.

        Only adds if echo is enabled for the channel.

        Args:
            channel_id: Discord Channel ID
            role: Message role ("user" or "assistant")
            content: Message content
            user_id: Discord User ID (for user messages)

        Returns:
            True if message was added, False if echo not enabled
        """
        if channel_id not in self.enabled_channels:
            return False

        # Ensure context list exists
        if channel_id not in self.channel_contexts:
            self.channel_contexts[channel_id] = []

        # Add message
        message = {
            "role": role,
            "content": content,
        }
        if user_id:
            message["user_id"] = user_id

        self.channel_contexts[channel_id].append(message)
        return True

    def get_context(self, channel_id: str) -> list[dict[str, Any]]:
        """Get the conversation context for a channel.

        Args:
            channel_id: Discord Channel ID

        Returns:
            List of message dicts, empty list if not enabled or no context
        """
        if channel_id not in self.enabled_channels:
            return []
        return self.channel_contexts.get(channel_id, [])

    def clear_context(self, channel_id: str) -> bool:
        """Clear the context for a channel without disabling echo.

        Args:
            channel_id: Discord Channel ID

        Returns:
            True if context was cleared, False if echo not enabled
        """
        if channel_id not in self.enabled_channels:
            return False

        self.channel_contexts[channel_id] = []
        return True

    def get_context_length(self, channel_id: str) -> int:
        """Get the number of messages in a channel's context.

        Args:
            channel_id: Discord Channel ID

        Returns:
            Number of messages in context, 0 if not enabled
        """
        if channel_id not in self.enabled_channels:
            return 0
        return len(self.channel_contexts.get(channel_id, []))

    # -------------------------------------------------------------- #
    # Persistence Methods
    # -------------------------------------------------------------- #

    async def load_enabled_channels_from_db(self, echo_sql_manager: "EchoSQLManagerService") -> int:
        """Load all enabled echo channels from the database into memory.

        This should be called during bot startup to restore echo states.
        Note: Context is NOT loaded from DB - it starts fresh each session.
        Only the enabled/disabled state is persisted.

        Args:
            echo_sql_manager: SQL manager to query enabled channels

        Returns:
            Number of enabled channels loaded
        """
        try:
            channel_ids = await echo_sql_manager.get_all_enabled_channel_ids()
            self.enabled_channels.update(channel_ids)

            # Initialize empty contexts for all loaded channels
            for channel_id in channel_ids:
                if channel_id not in self.channel_contexts:
                    self.channel_contexts[channel_id] = []

            await self.services.logging_service.info(
                f"Loaded {len(channel_ids)} echo-enabled channels from database"
            )
            return len(channel_ids)
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to load echo channels from database: {e}"
            )
            return 0

    def get_all_enabled_channels(self) -> set[str]:
        """Get all currently echo-enabled channel IDs.

        Returns:
            Set of channel IDs with echo enabled
        """
        return self.enabled_channels.copy()
