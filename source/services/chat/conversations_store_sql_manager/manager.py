from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select, update

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import ConversationsStoreModel
from source.services.manager import Manager
from source.utils import generate_16_char_uuid, get_current_timestamp_est

# -------------------------------------------------------------- #
# Conversations Store SQL Manager Service
# -------------------------------------------------------------- #


class ConversationsStoreSQLManagerService(Manager):
    """Service for managing conversations store SQL operations."""

    def __init__(self, context: "Context"):
        super().__init__(context)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("ConversationsStoreSQLManagerService initialized")
        return True

    async def on_close(self):
        await self.services.logging_service.info("ConversationsStoreSQLManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Conversations Store CRUD Methods
    # -------------------------------------------------------------- #

    async def insert_conversation_store(
        self,
        session_id: str,
        filename: str,
    ) -> str:
        """
        Insert a new conversation store entry.

        Args:
            session_id: Reference to the conversation ID (16 char UUID)
            filename: Path/filename where chat is persisted on disk

        Returns:
            store_id: The generated ID for the conversation store entry

        Raises:
            ValueError: If any required field is invalid
        """
        # Validate inputs
        if not session_id or len(session_id) != 16:
            raise ValueError("session_id must be 16 characters long")
        if not filename:
            raise ValueError("filename cannot be empty")

        # Generate entry data
        entry_id = generate_16_char_uuid()
        timestamp = get_current_timestamp_est()

        # Prepare store data
        store_data = {
            "id": entry_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "session_id": session_id,
            "filename": filename,
        }

        # Build and execute insert statement
        stmt = insert(ConversationsStoreModel).values(**store_data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Inserted conversation store: {entry_id} for session {session_id}"
        )

        return entry_id

    async def update_conversation_store_timestamp(self, store_id: str) -> None:
        """
        Update the updated_at timestamp of a conversation store entry (and nothing else).

        Args:
            store_id: The ID of the conversation store entry to update

        Raises:
            ValueError: If store_id is invalid
        """
        # Validate input
        if not store_id or len(store_id) != 16:
            raise ValueError("store_id must be 16 characters long")

        # Get current timestamp
        timestamp = get_current_timestamp_est()

        # Build update query
        stmt = (
            update(ConversationsStoreModel)
            .where(ConversationsStoreModel.id == store_id)
            .values(updated_at=timestamp)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.debug(
            f"Updated conversation store {store_id} timestamp"
        )

    async def retrieve_conversation_store_by_session_id(self, session_id: str) -> list[dict]:
        """
        Retrieve all conversation store entries for a specific session.

        Args:
            session_id: The session ID to search for

        Returns:
            List of conversation store dictionaries

        Raises:
            ValueError: If session_id is invalid
        """
        # Validate input
        if not session_id or len(session_id) != 16:
            raise ValueError("session_id must be 16 characters long")

        # Build select query
        query = select(ConversationsStoreModel).where(
            ConversationsStoreModel.session_id == session_id
        )

        # Execute query
        results = await self.server.sql_client.execute(query)

        await self.services.logging_service.debug(
            f"Found {len(results)} store entries for session: {session_id}"
        )
        return results if isinstance(results, list) else []

    async def retrieve_conversation_store_by_filename(self, filename: str) -> dict | None:
        """
        Retrieve a conversation store entry by filename.

        Args:
            filename: The filename to search for

        Returns:
            Conversation store dictionary if found, None otherwise

        Raises:
            ValueError: If filename is invalid
        """
        # Validate input
        if not filename:
            raise ValueError("filename cannot be empty")

        # Build select query
        query = select(ConversationsStoreModel).where(ConversationsStoreModel.filename == filename)

        # Execute query
        results = await self.server.sql_client.execute(query)

        # Handle result
        if results:
            store_entry = results[0]
            await self.services.logging_service.debug(
                f"Found conversation store with filename: {filename}"
            )
            return store_entry
        else:
            await self.services.logging_service.debug(
                f"No conversation store found with filename: {filename}"
            )
            return None

    async def retrieve_conversation_stores_by_time_range(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict]:
        """
        Retrieve conversation store entries within a time range.

        Args:
            start_time: Optional start timestamp (inclusive)
            end_time: Optional end timestamp (inclusive)

        Returns:
            List of conversation store dictionaries
        """
        # Build select query
        query = select(ConversationsStoreModel)

        # Add time filters if provided
        if start_time is not None:
            query = query.where(ConversationsStoreModel.created_at >= start_time)
        if end_time is not None:
            query = query.where(ConversationsStoreModel.created_at <= end_time)

        # Execute query
        results = await self.server.sql_client.execute(query)

        await self.services.logging_service.debug(
            f"Found {len(results)} store entries in time range"
        )
        return results if isinstance(results, list) else []

    async def delete_conversation_store_by_session_id_and_filename(
        self, session_id: str, filename: str
    ) -> None:
        """
        Delete a conversation store entry by session ID and filename.

        Args:
            session_id: The session ID of the store entry to delete
            filename: The filename of the store entry to delete

        Raises:
            ValueError: If session_id or filename is invalid
        """
        # Validate inputs
        if not session_id or len(session_id) != 16:
            raise ValueError("session_id must be 16 characters long")
        if not filename:
            raise ValueError("filename cannot be empty")

        # Build delete query
        query = delete(ConversationsStoreModel).where(
            ConversationsStoreModel.session_id == session_id,
            ConversationsStoreModel.filename == filename,
        )

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted conversation store for session {session_id} and filename {filename}"
        )

    async def delete_conversation_stores_by_session_id(self, session_id: str) -> None:
        """
        Delete all conversation store entries for a specific session.

        Args:
            session_id: The session ID of the store entries to delete

        Raises:
            ValueError: If session_id is invalid
        """
        # Validate input
        if not session_id or len(session_id) != 16:
            raise ValueError("session_id must be 16 characters long")

        # Build delete query
        query = delete(ConversationsStoreModel).where(
            ConversationsStoreModel.session_id == session_id
        )

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted all conversation stores for session: {session_id}"
        )
