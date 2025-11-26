from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from source.context import Context

from source.services.manager import BaseConversationFileServiceManager

# -------------------------------------------------------------- #
# Conversation File Manager Service
# -------------------------------------------------------------- #


class ConversationFileManagerService(BaseConversationFileServiceManager):
    """Service for managing conversation JSON files."""

    def __init__(self, context: Context, conversation_storage_path: str):
        super().__init__(context)
        self.conversation_storage_path = conversation_storage_path

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)

        # Run blocking filesystem operations in executor
        loop = asyncio.get_event_loop()

        # Check if folder exists, create if it doesn't
        if not await loop.run_in_executor(None, os.path.exists, self.conversation_storage_path):
            await loop.run_in_executor(None, os.makedirs, self.conversation_storage_path)

        await self.services.logging_service.info(
            f"ConversationFileManagerService initialized with storage path: {self.conversation_storage_path}"
        )
        return True

    async def on_close(self):
        await self.services.logging_service.info("ConversationFileManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Conversation File Management Methods
    # -------------------------------------------------------------- #

    def get_storage_path(self) -> str:
        """Get the absolute storage path."""
        return os.path.abspath(self.conversation_storage_path)

    def _build_conversation_filename(
        self, discord_user_id: str, guild_id: str, date: datetime | None = None
    ) -> str:
        """
        Build a standardized filename for a conversation.

        Args:
            discord_user_id: The Discord user ID
            guild_id: The guild ID
            date: Optional date for the conversation (defaults to today)

        Returns:
            Filename in format: yyyy-mm-dd_conversation-with-{discord_user_id}-in-{guild_id}.json
        """
        if date is None:
            date = datetime.now()

        date_str = date.strftime("%Y-%m-%d")
        return f"{date_str}_conversation-with-{discord_user_id}-in-{guild_id}.json"

    async def save_conversation(
        self,
        conversation_data: dict[str, Any],
        discord_user_id: str,
        guild_id: str,
        date: datetime | None = None,
    ) -> str:
        """
        Save a new conversation JSON file.

        Args:
            conversation_data: The conversation data to save
            discord_user_id: The Discord user ID
            guild_id: The guild ID
            date: Optional date for the conversation (defaults to today)

        Returns:
            The filename of the saved conversation

        Raises:
            ValueError: If conversation_data is empty or invalid
            FileExistsError: If conversation file already exists
            RuntimeError: If file save fails
        """
        if not conversation_data:
            raise ValueError("Conversation data cannot be empty")

        # Build filename
        filename = self._build_conversation_filename(discord_user_id, guild_id, date)
        # Build absolute path to ensure file_manager doesn't double-join
        file_path = os.path.abspath(os.path.join(self.conversation_storage_path, filename))

        try:
            # Convert to JSON bytes
            json_content = json.dumps(conversation_data, indent=2, ensure_ascii=False)
            data_bytes = json_content.encode("utf-8")

            # Use file_manager's atomic save operation (will raise FileExistsError if exists)
            await self.services.file_service_manager.save_file(file_path, data_bytes)

            await self.services.logging_service.info(
                f"Saved conversation file: {filename} ({len(data_bytes)} bytes)"
            )

            return filename

        except FileExistsError:
            await self.services.logging_service.warning(
                f"Conversation file already exists: {filename}"
            )
            raise
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to save conversation {filename}: {str(e)}"
            )
            raise RuntimeError(f"Failed to save conversation: {str(e)}") from e

    async def update_conversation(
        self,
        filename: str,
        conversation_data: dict[str, Any],
    ) -> bool:
        """
        Update an existing conversation JSON file with new data.

        This method uses the file_manager's atomic update operation to safely
        modify the conversation file.

        Args:
            filename: The name of the conversation file to update
            conversation_data: The complete updated conversation data

        Returns:
            True if update was successful, False if file doesn't exist

        Raises:
            RuntimeError: If update fails
        """
        # Build absolute path to ensure file_manager doesn't double-join
        file_path = os.path.abspath(os.path.join(self.conversation_storage_path, filename))

        try:
            # Convert conversation data to JSON bytes
            json_content = json.dumps(conversation_data, indent=2, ensure_ascii=False)
            data_bytes = json_content.encode("utf-8")

            # Use file_manager's update operation (accepts absolute paths)
            await self.services.file_service_manager.update_file(file_path, data_bytes)

            await self.services.logging_service.info(
                f"Updated conversation file: {filename} ({len(data_bytes)} bytes)"
            )

            return True

        except FileNotFoundError:
            await self.services.logging_service.warning(f"Conversation file not found: {filename}")
            return False
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update conversation {filename}: {str(e)}"
            )
            raise RuntimeError(f"Failed to update conversation: {str(e)}") from e

    async def retrieve_conversation(self, filename: str) -> dict[str, Any] | None:
        """
        Retrieve a conversation JSON file by filename.

        Args:
            filename: The name of the conversation file to retrieve

        Returns:
            The conversation JSON data as a dictionary, or None if not found

        Raises:
            RuntimeError: If file read fails
        """
        # Build absolute path to ensure file_manager doesn't double-join
        file_path = os.path.abspath(os.path.join(self.conversation_storage_path, filename))

        try:
            # Use file_manager's read operation (accepts absolute paths)
            data_bytes = await self.services.file_service_manager.read_file(file_path)
            conversation_data = json.loads(data_bytes.decode("utf-8"))

            await self.services.logging_service.info(f"Retrieved conversation: {filename}")

            return conversation_data

        except FileNotFoundError:
            await self.services.logging_service.warning(f"Conversation file not found: {filename}")
            return None
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to retrieve conversation {filename}: {str(e)}"
            )
            raise RuntimeError(f"Failed to retrieve conversation: {str(e)}") from e

    async def delete_conversation(self, filename: str) -> bool:
        """
        Delete a conversation JSON file.

        Args:
            filename: The name of the conversation file to delete

        Returns:
            True if deletion was successful, False if file was not found

        Raises:
            RuntimeError: If deletion fails
        """
        # Build absolute path to ensure file_manager doesn't double-join
        file_path = os.path.abspath(os.path.join(self.conversation_storage_path, filename))

        try:
            # Use file_manager's delete operation (will check existence internally)
            await self.services.file_service_manager.delete_file(file_path)

            await self.services.logging_service.info(f"Deleted conversation file: {filename}")

            return True

        except FileNotFoundError:
            await self.services.logging_service.warning(
                f"Conversation file not found (already deleted?): {filename}"
            )
            return False
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to delete conversation {filename}: {str(e)}"
            )
            raise RuntimeError(f"Failed to delete conversation: {str(e)}") from e

    async def conversation_exists(self, filename: str) -> bool:
        """
        Check if a conversation file exists.

        Args:
            filename: The name of the conversation file to check

        Returns:
            True if conversation exists, False otherwise
        """
        # Build absolute path to ensure file_manager doesn't double-join
        file_path = os.path.abspath(os.path.join(self.conversation_storage_path, filename))

        try:
            return await self.services.file_service_manager.file_exists(file_path)
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to check if conversation exists {filename}: {str(e)}"
            )
            return False

    async def list_conversations(self) -> list[str]:
        """
        List all conversation files in the storage directory.

        Returns:
            List of conversation filenames
        """
        try:
            loop = asyncio.get_event_loop()
            filenames = await loop.run_in_executor(None, os.listdir, self.conversation_storage_path)

            # Filter only JSON files
            conversation_files = [f for f in filenames if f.endswith(".json")]

            await self.services.logging_service.info(
                f"Listed {len(conversation_files)} conversation files"
            )

            return conversation_files

        except Exception as e:
            await self.services.logging_service.error(f"Failed to list conversations: {str(e)}")
            return []

    async def get_conversation_by_user_and_guild_and_date(
        self, discord_user_id: str, guild_id: str, date: datetime | None = None
    ) -> dict[str, Any] | None:
        """
        Retrieve a conversation by user ID, guild ID, and date.

        This is a convenience method that builds the filename and retrieves the conversation.

        Args:
            discord_user_id: The Discord user ID
            guild_id: The guild ID
            date: Optional date for the conversation (defaults to today)

        Returns:
            The conversation data as a dictionary, or None if not found
        """
        filename = self._build_conversation_filename(discord_user_id, guild_id, date)
        return await self.retrieve_conversation(filename)
