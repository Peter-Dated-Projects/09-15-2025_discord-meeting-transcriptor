"""In-memory conversation cache management system.

This module provides in-memory storage and management of ongoing conversations
with automatic cleanup after idle periods.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from source.services.conversation_file_manager.manager import (
        BaseConversationFileServiceManager,
    )


# -------------------------------------------------------------- #
# Message Type Enum
# -------------------------------------------------------------- #


class MessageType(Enum):
    """Enum representing different types of messages in a conversation."""

    THINKING = "thinking"
    CHAT = "chat"
    TOOL_CALL = "tool_call"
    TOOL_CALL_RESPONSE = "tool_call_response"


# -------------------------------------------------------------- #
# Conversation Status Enum
# -------------------------------------------------------------- #


class ConversationStatus(Enum):
    """Enum representing the status of a conversation."""

    IDLE = "idle"
    THINKING = "thinking"
    PROCESSING_QUEUE = "processing_queue"


# -------------------------------------------------------------- #
# Message Object
# -------------------------------------------------------------- #


@dataclass
class Message:
    """Represents a single message in a conversation.

    Attributes:
        created_at: Timestamp when the message was created
        message_type: Type of message (thinking, chat, tool_call, tool_call_response)
        message_content: The actual content of the message
        tools: List of tool calls (only for tool_call type)
        requester: Discord user ID of the requester (only for user messages)
    """

    created_at: datetime
    message_type: MessageType
    message_content: str
    tools: Optional[List[Dict[str, Any]]] = None
    requester: Optional[str] = None

    def to_json(self) -> Dict[str, Any]:
        """Convert the message to JSON-serializable format.

        Returns:
            Dictionary representation of the message
        """
        json_data: Dict[str, Any] = {
            "created_at": self.created_at.isoformat(),
            "message_type": self.message_type.value,
            "message_content": self.message_content,
            "meta": {},
        }

        # Add tools to meta if present
        if self.tools:
            json_data["meta"]["tools"] = self.tools

        # Add requester to meta if present
        if self.requester:
            json_data["meta"]["requester"] = self.requester

        return json_data

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> Message:
        """Create a Message instance from JSON data.

        Args:
            data: Dictionary containing message data

        Returns:
            Message instance
        """
        meta = data.get("meta", {})

        return cls(
            created_at=datetime.fromisoformat(data["created_at"]),
            message_type=MessageType(data["message_type"]),
            message_content=data["message_content"],
            tools=meta.get("tools"),
            requester=meta.get("requester"),
        )


# -------------------------------------------------------------- #
# Conversation Object
# -------------------------------------------------------------- #


@dataclass
class Conversation:
    """Represents a conversation with its metadata and message history.

    Attributes:
        thread_id: Discord thread ID where the conversation is taking place
        created_at: Timestamp when the conversation was created
        updated_at: Timestamp when the conversation was last updated
        summary: Summary of the conversation
        guild_id: Discord guild ID
        guild_name: Discord guild name
        requester: Discord user ID of the user who started the conversation
        participants: List of Discord user IDs participating in the conversation
        history: List of messages in the conversation
        filename: Designated filename for saving the conversation
        conversation_file_manager: Reference to the file manager service
        status: Current status of the conversation (idle, thinking, processing_queue)
    """

    thread_id: str
    created_at: datetime
    guild_id: str
    guild_name: str
    requester: str
    conversation_file_manager: Optional[BaseConversationFileServiceManager] = None
    updated_at: Optional[datetime] = None
    summary: str = ""
    participants: List[str] = field(default_factory=list)
    history: List[Message] = field(default_factory=list)
    filename: str = ""
    status: ConversationStatus = ConversationStatus.IDLE

    def __post_init__(self):
        """Initialize computed fields after dataclass initialization."""
        if self.updated_at is None:
            self.updated_at = self.created_at

        if not self.participants:
            self.participants = [self.requester]

        # Generate filename: yyyy-mm-dd_conversation-with-{user_id}-in-{guild_id}.json
        date_str = self.created_at.strftime("%Y-%m-%d")
        self.filename = f"{date_str}_conversation-with-{self.requester}-in-{self.guild_id}.json"

    def add_message(self, message: Message) -> None:
        """Add a message to the conversation history.

        Args:
            message: Message to add to the conversation
        """
        self.history.append(message)
        self.updated_at = datetime.now()

        # Add to participants if it's a user message with a requester
        if message.requester and message.requester not in self.participants:
            self.participants.append(message.requester)

    def to_json(self) -> Dict[str, Any]:
        """Convert the conversation to JSON-serializable format.

        Returns:
            Dictionary representation of the conversation
        """
        return {
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "summary": self.summary,
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "requester": self.requester,
            "participants": self.participants,
            "history": [message.to_json() for message in self.history],
        }

    @classmethod
    def from_json(
        cls,
        data: Dict[str, Any],
        thread_id: str,
        conversation_file_manager: Optional[BaseConversationFileServiceManager] = None,
    ) -> Conversation:
        """Create a Conversation instance from JSON data.

        Args:
            data: Dictionary containing conversation data
            thread_id: Discord thread ID
            conversation_file_manager: Reference to the file manager service

        Returns:
            Conversation instance
        """
        history = [Message.from_json(msg_data) for msg_data in data.get("history", [])]

        return cls(
            thread_id=thread_id,
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=(
                datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None
            ),
            summary=data.get("summary", ""),
            guild_id=data["guild_id"],
            guild_name=data["guild_name"],
            requester=data["requester"],
            participants=data.get("participants", []),
            history=history,
            conversation_file_manager=conversation_file_manager,
        )

    async def save_conversation(self) -> bool:
        """Save the conversation to disk via the conversation_file_manager.

        Returns:
            True if save was successful, False otherwise
        """
        if not self.conversation_file_manager:
            raise ValueError("conversation_file_manager is not set. Cannot save conversation.")

        try:
            # Convert to JSON
            conversation_data = self.to_json()

            # Check if file already exists
            exists = await self.conversation_file_manager.conversation_exists(
                filename=self.filename
            )

            if exists:
                # Update existing conversation
                success = await self.conversation_file_manager.update_conversation(
                    filename=self.filename, conversation_data=conversation_data
                )
            else:
                # Save new conversation
                await self.conversation_file_manager.save_conversation(
                    conversation_data=conversation_data,
                    discord_user_id=self.requester,
                    guild_id=self.guild_id,
                )
                success = True

            return success

        except Exception as e:
            # TODO: Add proper logging here
            print(f"Error saving conversation: {e}")
            return False


# -------------------------------------------------------------- #
# In-Memory Conversation Manager
# -------------------------------------------------------------- #


class InMemoryConversationManager:
    """Manages in-memory conversations with automatic cleanup after idle periods.

    Attributes:
        IDLE_TIME: Time in seconds after which a conversation is removed from memory
        conversations: Dictionary mapping thread IDs to Conversation objects
        cleanup_tasks: Dictionary mapping thread IDs to cleanup task handles
    """

    # 5 minutes in seconds
    IDLE_TIME: int = 5 * 60

    def __init__(
        self,
        conversation_file_manager: Optional[BaseConversationFileServiceManager] = None,
    ):
        """Initialize the in-memory conversation manager.

        Args:
            conversation_file_manager: Reference to the file manager service
        """
        self.conversations: Dict[str, Conversation] = {}
        self.cleanup_tasks: Dict[str, asyncio.Task] = {}
        self.conversation_file_manager = conversation_file_manager

    def create_conversation(
        self,
        thread_id: str,
        guild_id: str,
        guild_name: str,
        requester: str,
    ) -> Conversation:
        """Create a new conversation and store it in memory.

        Args:
            thread_id: Discord thread ID
            guild_id: Discord guild ID
            guild_name: Discord guild name
            requester: Discord user ID of the requester

        Returns:
            The newly created Conversation object
        """
        # Cancel existing cleanup task if any
        if thread_id in self.cleanup_tasks:
            self.cleanup_tasks[thread_id].cancel()
            del self.cleanup_tasks[thread_id]

        # Create new conversation
        conversation = Conversation(
            thread_id=thread_id,
            created_at=datetime.now(),
            guild_id=guild_id,
            guild_name=guild_name,
            requester=requester,
            conversation_file_manager=self.conversation_file_manager,
        )

        # Store in memory
        self.conversations[thread_id] = conversation

        # Schedule cleanup
        self._schedule_cleanup(thread_id)

        return conversation

    def get_conversation(self, thread_id: str) -> Optional[Conversation]:
        """Retrieve a conversation from memory.

        Args:
            thread_id: Discord thread ID

        Returns:
            Conversation object if found, None otherwise
        """
        return self.conversations.get(thread_id)

    def add_message_to_conversation(
        self, thread_id: str, message: Message
    ) -> Optional[Conversation]:
        """Add a message to an existing conversation and reset its idle timer.

        Args:
            thread_id: Discord thread ID
            message: Message to add

        Returns:
            Updated Conversation object if found, None otherwise
        """
        conversation = self.conversations.get(thread_id)

        if conversation:
            conversation.add_message(message)

            # Reset the cleanup timer
            if thread_id in self.cleanup_tasks:
                self.cleanup_tasks[thread_id].cancel()

            self._schedule_cleanup(thread_id)

        return conversation

    def remove_conversation(self, thread_id: str) -> None:
        """Remove a conversation from memory immediately.

        Args:
            thread_id: Discord thread ID
        """
        # Cancel cleanup task if exists
        if thread_id in self.cleanup_tasks:
            self.cleanup_tasks[thread_id].cancel()
            del self.cleanup_tasks[thread_id]

        # Remove conversation
        if thread_id in self.conversations:
            del self.conversations[thread_id]

    def _schedule_cleanup(self, thread_id: str) -> None:
        """Schedule automatic cleanup of a conversation after IDLE_TIME.

        Args:
            thread_id: Discord thread ID
        """
        task = asyncio.create_task(self._cleanup_after_idle(thread_id))
        self.cleanup_tasks[thread_id] = task

    async def _cleanup_after_idle(self, thread_id: str) -> None:
        """Wait for IDLE_TIME and then remove the conversation from memory.

        Args:
            thread_id: Discord thread ID
        """
        try:
            await asyncio.sleep(self.IDLE_TIME)

            # Remove from memory after idle time
            if thread_id in self.conversations:
                del self.conversations[thread_id]

            if thread_id in self.cleanup_tasks:
                del self.cleanup_tasks[thread_id]

        except asyncio.CancelledError:
            # Task was cancelled (conversation was updated)
            pass

    def get_all_conversations(self) -> Dict[str, Conversation]:
        """Get all active conversations in memory.

        Returns:
            Dictionary of all active conversations
        """
        return self.conversations.copy()

    async def save_all_conversations(self) -> Dict[str, bool]:
        """Save all active conversations to disk.

        Returns:
            Dictionary mapping thread IDs to save success status
        """
        results: Dict[str, bool] = {}

        for thread_id, conversation in self.conversations.items():
            success = await conversation.save_conversation()
            results[thread_id] = success

        return results

    async def shutdown(self) -> None:
        """Gracefully shutdown the manager by cancelling all cleanup tasks."""
        for task in self.cleanup_tasks.values():
            task.cancel()

        self.cleanup_tasks.clear()
