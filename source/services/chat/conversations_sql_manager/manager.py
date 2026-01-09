from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select, update

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import ConversationsModel
from source.services.manager import Manager
from source.utils import generate_16_char_uuid, get_current_timestamp_est

# -------------------------------------------------------------- #
# Conversations SQL Manager Service
# -------------------------------------------------------------- #


class ConversationsSQLManagerService(Manager):
    """Service for managing conversations SQL operations."""

    def __init__(self, context: "Context"):
        super().__init__(context)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("ConversationsSQLManagerService initialized")
        return True

    async def on_close(self):
        await self.services.logging_service.info("ConversationsSQLManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Conversation CRUD Methods
    # -------------------------------------------------------------- #

    async def insert_conversation(
        self,
        discord_thread_id: str,
        discord_requester_id: str,
        discord_guild_id: str,
        chat_meta: dict | None = None,
    ) -> str:
        """
        Insert a new conversation entry.

        Args:
            discord_thread_id: Discord Thread ID where the chat is located
            discord_requester_id: Discord User ID of the requester
            discord_guild_id: Discord Guild (Server) ID
            chat_meta: Optional JSON metadata (defaults to empty dict)

        Returns:
            conversation_id: The generated ID for the conversation

        Raises:
            ValueError: If any required field is invalid
        """
        # Validate inputs
        if not discord_thread_id or len(discord_thread_id) < 16:
            raise ValueError("discord_thread_id must be at least 16 characters long")
        if not discord_requester_id or len(discord_requester_id) < 16:
            raise ValueError("discord_requester_id must be at least 16 characters long")
        if not discord_guild_id or len(discord_guild_id) < 17:
            raise ValueError("discord_guild_id must be at least 17 characters long")

        # Generate entry data
        entry_id = generate_16_char_uuid()
        timestamp = get_current_timestamp_est()

        # Prepare conversation data
        conversation_data = {
            "id": entry_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "discord_thread_id": discord_thread_id,
            "chat_meta": chat_meta if chat_meta is not None else {},
            "discord_requester_id": discord_requester_id,
            "discord_guild_id": discord_guild_id,
            "monitoring_stopped": 0,
        }

        # Build and execute insert statement
        stmt = insert(ConversationsModel).values(**conversation_data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Inserted conversation: {entry_id} for thread {discord_thread_id}"
        )

        return entry_id

    async def update_conversation_timestamp(self, conversation_id: str) -> None:
        """
        Update the updated_at timestamp of a conversation (and nothing else).

        Args:
            conversation_id: The ID of the conversation to update

        Raises:
            ValueError: If conversation_id is invalid
        """
        # Validate input
        if not conversation_id or len(conversation_id) != 16:
            raise ValueError("conversation_id must be 16 characters long")

        # Get current timestamp
        timestamp = get_current_timestamp_est()

        # Build update query
        stmt = (
            update(ConversationsModel)
            .where(ConversationsModel.id == conversation_id)
            .values(updated_at=timestamp)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.debug(
            f"Updated conversation {conversation_id} timestamp"
        )

    async def retrieve_conversation_by_id(self, conversation_id: str) -> dict | None:
        """
        Retrieve a conversation by its ID.

        Args:
            conversation_id: The ID of the conversation to retrieve

        Returns:
            Conversation dictionary if found, None otherwise

        Raises:
            ValueError: If conversation_id is invalid
        """
        # Validate input
        if not conversation_id or len(conversation_id) != 16:
            raise ValueError("conversation_id must be 16 characters long")

        # Build select query
        query = select(ConversationsModel).where(ConversationsModel.id == conversation_id)

        # Execute query
        results = await self.server.sql_client.execute(query)

        # Handle result
        if results:
            conversation = results[0]
            await self.services.logging_service.debug(
                f"Found conversation with ID: {conversation_id}"
            )
            return conversation
        else:
            await self.services.logging_service.debug(
                f"No conversation found with ID: {conversation_id}"
            )
            return None

    async def retrieve_conversation_by_thread_id(self, discord_thread_id: str) -> dict | None:
        """
        Retrieve a conversation by Discord thread ID.

        Args:
            discord_thread_id: Discord Thread ID to search for

        Returns:
            Conversation dictionary if found, None otherwise

        Raises:
            ValueError: If discord_thread_id is invalid
        """
        # Validate input
        if not discord_thread_id or len(discord_thread_id) < 16:
            raise ValueError("discord_thread_id must be at least 16 characters long")

        # Build select query
        query = select(ConversationsModel).where(
            ConversationsModel.discord_thread_id == discord_thread_id
        )

        # Execute query
        results = await self.server.sql_client.execute(query)

        # Handle result
        if results:
            conversation = results[0]
            await self.services.logging_service.debug(
                f"Found conversation with thread ID: {discord_thread_id}"
            )
            return conversation
        else:
            await self.services.logging_service.debug(
                f"No conversation found with thread ID: {discord_thread_id}"
            )
            return None

    async def retrieve_conversations_by_requester_id(self, discord_requester_id: str) -> list[dict]:
        """
        Retrieve all conversations for a specific requesting user.

        Args:
            discord_requester_id: Discord User ID of the requester

        Returns:
            List of conversation dictionaries

        Raises:
            ValueError: If discord_requester_id is invalid
        """
        # Validate input
        if not discord_requester_id or len(discord_requester_id) < 16:
            raise ValueError("discord_requester_id must be at least 16 characters long")

        # Build select query
        query = select(ConversationsModel).where(
            ConversationsModel.discord_requester_id == discord_requester_id
        )

        # Execute query
        results = await self.server.sql_client.execute(query)

        await self.services.logging_service.debug(
            f"Found {len(results)} conversations for requester: {discord_requester_id}"
        )
        return results if isinstance(results, list) else []

    async def update_monitoring_stopped(
        self, discord_thread_id: str, monitoring_stopped: bool
    ) -> bool:
        """Update the monitoring_stopped status for a conversation.

        Args:
            discord_thread_id: Discord Thread ID
            monitoring_stopped: True to stop monitoring, False to resume

        Returns:
            True if update was successful, False if conversation not found
        """
        if not discord_thread_id or len(discord_thread_id) < 16:
            raise ValueError("discord_thread_id must be at least 16 characters long")

        # Convert boolean to integer (0 or 1) for SQLite
        monitoring_value = 1 if monitoring_stopped else 0

        # Build update query
        stmt = (
            update(ConversationsModel)
            .where(ConversationsModel.discord_thread_id == discord_thread_id)
            .values(monitoring_stopped=monitoring_value, updated_at=get_current_timestamp_est())
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Updated monitoring_stopped={monitoring_stopped} for thread {discord_thread_id}"
        )
        return True

    async def get_all_stopped_thread_ids(self) -> list[str]:
        """Retrieve all thread IDs that have monitoring stopped.

        Returns:
            List of Discord thread IDs with monitoring stopped
        """
        # Build select query for threads with monitoring_stopped = 1
        query = select(ConversationsModel.discord_thread_id).where(
            ConversationsModel.monitoring_stopped == 1
        )

        # Execute query
        results = await self.server.sql_client.execute(query)

        # Extract thread IDs from results
        thread_ids = [row["discord_thread_id"] for row in results] if results else []

        await self.services.logging_service.debug(
            f"Found {len(thread_ids)} threads with monitoring stopped"
        )
        return thread_ids

    async def retrieve_conversations_by_guild_id(self, discord_guild_id: str) -> list[dict]:
        """
        Retrieve all conversations for a specific guild.

        Args:
            discord_guild_id: Discord Guild (Server) ID

        Returns:
            List of conversation dictionaries

        Raises:
            ValueError: If discord_guild_id is invalid
        """
        # Validate input
        if not discord_guild_id or len(discord_guild_id) < 17:
            raise ValueError("discord_guild_id must be at least 17 characters long")

        # Build select query
        query = select(ConversationsModel).where(
            ConversationsModel.discord_guild_id == discord_guild_id
        )

        # Execute query
        results = await self.server.sql_client.execute(query)

        await self.services.logging_service.debug(
            f"Found {len(results)} conversations for guild: {discord_guild_id}"
        )
        return results if isinstance(results, list) else []

    async def get_all_thread_ids(self) -> list[str]:
        """
        Retrieve all Discord thread IDs from the conversations table.

        This is optimized to return only the thread IDs for efficient caching.

        Returns:
            List of Discord thread IDs

        Raises:
            Exception: If query fails
        """
        try:
            # Build select query for just the thread_id column
            query = select(ConversationsModel.discord_thread_id)

            # Execute query
            results = await self.server.sql_client.execute(query)

            # Extract thread IDs from results
            thread_ids = []
            if results:
                # Results should be a list of Row objects or dicts
                for row in results:
                    if isinstance(row, dict):
                        thread_ids.append(row.get("discord_thread_id"))
                    else:
                        # If it's a Row object with attributes
                        thread_ids.append(
                            row.discord_thread_id
                            if hasattr(row, "discord_thread_id")
                            else str(row[0])
                        )

            await self.services.logging_service.debug(
                f"Retrieved {len(thread_ids)} thread IDs from conversations table"
            )
            return thread_ids

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to retrieve thread IDs: {e}", exc_info=True
            )
            # Return empty list on error rather than failing
            return []

    async def retrieve_conversations_by_time_range(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict]:
        """
        Retrieve conversations within a time range.

        Args:
            start_time: Optional start timestamp (inclusive)
            end_time: Optional end timestamp (inclusive)

        Returns:
            List of conversation dictionaries
        """
        # Build select query
        query = select(ConversationsModel)

        # Add time filters if provided
        if start_time is not None:
            query = query.where(ConversationsModel.created_at >= start_time)
        if end_time is not None:
            query = query.where(ConversationsModel.created_at <= end_time)

        # Execute query
        results = await self.server.sql_client.execute(query)

        await self.services.logging_service.debug(
            f"Found {len(results)} conversations in time range"
        )
        return results if isinstance(results, list) else []

    async def delete_conversation_by_id(self, conversation_id: str) -> None:
        """
        Delete a conversation by its ID.

        Args:
            conversation_id: The ID of the conversation to delete

        Raises:
            ValueError: If conversation_id is invalid
        """
        # Validate input
        if not conversation_id or len(conversation_id) != 16:
            raise ValueError("conversation_id must be 16 characters long")

        # Build delete query
        query = delete(ConversationsModel).where(ConversationsModel.id == conversation_id)

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(f"Deleted conversation: {conversation_id}")

    async def delete_conversation_by_thread_id(self, discord_thread_id: str) -> None:
        """
        Delete a conversation by Discord thread ID.

        Args:
            discord_thread_id: Discord Thread ID of the conversation to delete

        Raises:
            ValueError: If discord_thread_id is invalid
        """
        # Validate input
        if not discord_thread_id or len(discord_thread_id) < 16:
            raise ValueError("discord_thread_id must be at least 16 characters long")

        # Build delete query
        query = delete(ConversationsModel).where(
            ConversationsModel.discord_thread_id == discord_thread_id
        )

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted conversation with thread ID: {discord_thread_id}"
        )

    async def delete_conversations_by_guild_id(self, discord_guild_id: str) -> None:
        """
        Delete all conversations for a specific guild.

        Args:
            discord_guild_id: Discord Guild (Server) ID

        Raises:
            ValueError: If discord_guild_id is invalid
        """
        # Validate input
        if not discord_guild_id or len(discord_guild_id) < 17:
            raise ValueError("discord_guild_id must be at least 17 characters long")

        # Build delete query
        query = delete(ConversationsModel).where(
            ConversationsModel.discord_guild_id == discord_guild_id
        )

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted all conversations for guild: {discord_guild_id}"
        )
