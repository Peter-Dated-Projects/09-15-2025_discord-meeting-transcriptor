from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select, update

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import ConversationsModel
from source.services.manager import Manager
from source.utils import (
    DISCORD_USER_ID_MIN_LENGTH,
    generate_16_char_uuid,
    get_current_timestamp_est,
)

# -------------------------------------------------------------- #
# Chatbot SQL Manager Service
# -------------------------------------------------------------- #


class ChatbotSQLManagerService(Manager):
    """Service for managing SQL operations for conversations/chatbot."""

    def __init__(self, context: "Context"):
        super().__init__(context)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("ChatbotSQLManagerService initialized")
        return True

    async def on_close(self):
        await self.services.logging_service.info("ChatbotSQLManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Conversations CRUD Methods
    # -------------------------------------------------------------- #

    async def insert_conversation(
        self,
        conversation_file: str,
        discord_guild_id: str,
        discord_message_id: str,
        requesting_user_id: str,
    ) -> str:
        """
        Insert a new conversation entry when a chat session is started.

        Args:
            conversation_file: Path to the JSON file containing conversation history
            discord_guild_id: Discord Guild (Server) ID (required)
            discord_message_id: Discord Message ID of thread starter message (required)
            requesting_user_id: Discord User ID of the user who initiated the conversation (required)

        Returns:
            conversation_id: The generated ID for the conversation
        """

        # Validate inputs
        if not conversation_file or len(conversation_file) == 0:
            raise ValueError("conversation_file cannot be empty")

        if len(discord_guild_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"discord_guild_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        if len(discord_message_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"discord_message_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        if len(requesting_user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"requesting_user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        # Generate entry data
        entry_id = generate_16_char_uuid()
        timestamp = get_current_timestamp_est()

        conversation = ConversationsModel(
            id=entry_id,
            created_at=timestamp,
            updated_at=timestamp,
            conversation_file=conversation_file,
            discord_guild_id=discord_guild_id,
            discord_message_id=discord_message_id,
            requesting_user_id=requesting_user_id,
        )

        # Convert to dict for insertion
        conversation_data = {
            "id": conversation.id,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "conversation_file": conversation.conversation_file,
            "discord_guild_id": conversation.discord_guild_id,
            "discord_message_id": conversation.discord_message_id,
            "requesting_user_id": conversation.requesting_user_id,
        }

        # Build and execute insert statement
        stmt = insert(ConversationsModel).values(**conversation_data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(f"Inserted conversation: {entry_id}")

        return entry_id

    async def delete_conversation(self, conversation_id: str) -> None:
        """
        Delete a conversation entry by its ID.

        Args:
            conversation_id: The ID of the conversation to delete
        """

        # Validate input
        if len(conversation_id) != 16:
            raise ValueError("conversation_id must be 16 characters long")

        # Build delete query
        query = delete(ConversationsModel).where(ConversationsModel.id == conversation_id)

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(f"Deleted conversation: {conversation_id}")

    async def delete_conversations(self, conversation_ids: list[str]) -> None:
        """
        Delete multiple conversation entries by their IDs.

        Args:
            conversation_ids: List of conversation IDs to delete
        """

        # Validate input
        for entry_id in conversation_ids:
            if len(entry_id) != 16:
                raise ValueError("All conversation_ids must be 16 characters long")

        # Build delete query
        query = delete(ConversationsModel).where(ConversationsModel.id.in_(conversation_ids))

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(f"Deleted {len(conversation_ids)} conversations")

    async def update_conversation(
        self,
        conversation_id: str,
        conversation_file: str | None = None,
        discord_guild_id: str | None = None,
        discord_message_id: str | None = None,
        requesting_user_id: str | None = None,
    ) -> None:
        """
        Update a conversation entry by its ID.

        Args:
            conversation_id: The ID of the conversation to update
            conversation_file: New path to the JSON file containing conversation history (optional)
            discord_guild_id: New Discord Guild (Server) ID (optional)
            discord_message_id: New Discord Message ID (optional)
            requesting_user_id: New Discord User ID of the user who initiated the conversation (optional)

        Note:
            Only provided fields will be updated. Pass None to keep existing values.
            The updated_at timestamp is always updated automatically.
        """

        # Validate conversation_id
        if len(conversation_id) != 16:
            raise ValueError("conversation_id must be 16 characters long")

        # Build update values dict with only provided fields
        update_values = {"updated_at": get_current_timestamp_est()}

        if conversation_file is not None:
            if len(conversation_file) == 0:
                raise ValueError("conversation_file cannot be empty")
            update_values["conversation_file"] = conversation_file

        if discord_guild_id is not None:
            if len(discord_guild_id) < DISCORD_USER_ID_MIN_LENGTH:
                raise ValueError(
                    f"discord_guild_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
                )
            update_values["discord_guild_id"] = discord_guild_id

        if discord_message_id is not None:
            if len(discord_message_id) < DISCORD_USER_ID_MIN_LENGTH:
                raise ValueError(
                    f"discord_message_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
                )
            update_values["discord_message_id"] = discord_message_id

        if requesting_user_id is not None:
            if len(requesting_user_id) < DISCORD_USER_ID_MIN_LENGTH:
                raise ValueError(
                    f"requesting_user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
                )
            update_values["requesting_user_id"] = requesting_user_id

        # Build update query
        stmt = (
            update(ConversationsModel)
            .where(ConversationsModel.id == conversation_id)
            .values(**update_values)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Updated conversation {conversation_id} with fields: {list(update_values.keys())}"
        )

    # -------------------------------------------------------------- #
    # Conversations Query Methods
    # -------------------------------------------------------------- #

    async def get_conversation(self, conversation_id: str) -> dict:
        """
        Get conversation details by conversation ID.

        Args:
            conversation_id: Conversation ID (16 chars)

        Returns:
            Conversation details as a dictionary

        Raises:
            ValueError: If conversation not found
        """

        # Validate input
        if len(conversation_id) != 16:
            raise ValueError("conversation_id must be 16 characters long")

        # Build and execute query
        query = select(ConversationsModel).where(ConversationsModel.id == conversation_id)
        results = await self.server.sql_client.execute(query)

        if results:
            return results[0]
        else:
            raise ValueError(f"Conversation with ID {conversation_id} not found")

    async def get_conversations_by_user(self, requesting_user_id: str) -> list[dict]:
        """
        Get all conversations initiated by a specific user.

        Args:
            requesting_user_id: Discord User ID (at least 16 chars)

        Returns:
            List of conversation details as dictionaries
        """

        # Validate input
        if len(requesting_user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"requesting_user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        # Build and execute query
        query = select(ConversationsModel).where(
            ConversationsModel.requesting_user_id == requesting_user_id
        )
        results = await self.server.sql_client.execute(query)

        return results if results else []

    async def get_conversations_by_guild(self, discord_guild_id: str) -> list[dict]:
        """
        Get all conversations in a specific Discord guild.

        Args:
            discord_guild_id: Discord Guild (Server) ID (at least 16 chars)

        Returns:
            List of conversation details as dictionaries
        """

        # Validate input
        if len(discord_guild_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"discord_guild_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        # Build and execute query
        query = select(ConversationsModel).where(
            ConversationsModel.discord_guild_id == discord_guild_id
        )
        results = await self.server.sql_client.execute(query)

        return results if results else []

    async def get_conversation_by_message_id(self, discord_message_id: str) -> dict:
        """
        Get conversation details by Discord message ID.

        Args:
            discord_message_id: Discord Message ID (at least 16 chars)

        Returns:
            Conversation details as a dictionary

        Raises:
            ValueError: If conversation not found
        """

        # Validate input
        if len(discord_message_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"discord_message_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        # Build and execute query
        query = select(ConversationsModel).where(
            ConversationsModel.discord_message_id == discord_message_id
        )
        results = await self.server.sql_client.execute(query)

        if results:
            return results[0]
        else:
            raise ValueError(f"Conversation with message ID {discord_message_id} not found")
