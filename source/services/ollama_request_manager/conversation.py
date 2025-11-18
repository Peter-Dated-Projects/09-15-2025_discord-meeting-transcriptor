"""
Conversation History Management.

This module provides conversation history tracking for multi-turn
chat interactions with Ollama. It handles:
- Message history storage
- Automatic truncation based on length or token count
- Session-based organization
- Message role management

Usage:
    history = ConversationHistory(session_id="user_123")
    history.add_user_message("Hello!")
    history.add_assistant_message("Hi there!")
    messages = history.get_messages()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ConversationMessage:
    """A single message in a conversation."""

    role: Literal["system", "user", "assistant"]
    content: str
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    metadata: dict = field(default_factory=dict)


class ConversationHistory:
    """
    Manages conversation history for a single session.

    This class tracks all messages in a conversation and provides
    automatic history management with configurable limits.
    """

    def __init__(
        self,
        session_id: str,
        max_length: int = 50,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
    ):
        """
        Initialize conversation history.

        Args:
            session_id: Unique identifier for this conversation
            max_length: Maximum number of messages to keep
            max_tokens: Maximum total tokens (if set, approximate by word count)
            system_prompt: Optional system prompt for this conversation
        """
        self.session_id = session_id
        self.max_length = max_length
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt

        self._messages: list[ConversationMessage] = []
        self._total_user_messages = 0
        self._total_assistant_messages = 0

    # -------------------------------------------------------------- #
    # Message Management
    # -------------------------------------------------------------- #

    def add_message(
        self, role: Literal["system", "user", "assistant"], content: str, metadata: dict | None = None
    ) -> None:
        """
        Add a message to the conversation history.

        Args:
            role: Message role (system, user, or assistant)
            content: Message content
            metadata: Optional metadata for the message
        """
        message = ConversationMessage(role=role, content=content, metadata=metadata or {})
        self._messages.append(message)

        # Track message counts
        if role == "user":
            self._total_user_messages += 1
        elif role == "assistant":
            self._total_assistant_messages += 1

        # Enforce limits
        self._enforce_limits()

    def add_user_message(self, content: str, metadata: dict | None = None) -> None:
        """Add a user message to history."""
        self.add_message("user", content, metadata)

    def add_assistant_message(self, content: str, metadata: dict | None = None) -> None:
        """Add an assistant message to history."""
        self.add_message("assistant", content, metadata)

    def add_system_message(self, content: str, metadata: dict | None = None) -> None:
        """Add a system message to history."""
        self.add_message("system", content, metadata)

    # -------------------------------------------------------------- #
    # History Retrieval
    # -------------------------------------------------------------- #

    def get_messages(self, include_system: bool = False) -> list[dict[str, str]]:
        """
        Get all messages in the conversation.

        Args:
            include_system: Whether to include system messages

        Returns:
            List of message dicts with 'role' and 'content'
        """
        messages = []

        # Add system prompt if set
        if self.system_prompt and include_system:
            messages.append({"role": "system", "content": self.system_prompt})

        # Add conversation messages
        for msg in self._messages:
            if msg.role == "system" and not include_system:
                continue
            messages.append({"role": msg.role, "content": msg.content})

        return messages

    def get_last_n_messages(self, n: int) -> list[dict[str, str]]:
        """Get the last N messages."""
        return [
            {"role": msg.role, "content": msg.content} for msg in self._messages[-n:]
        ]

    def get_messages_since(self, timestamp: float) -> list[dict[str, str]]:
        """Get all messages after a specific timestamp."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self._messages
            if msg.timestamp > timestamp
        ]

    # -------------------------------------------------------------- #
    # History Management
    # -------------------------------------------------------------- #

    def clear(self) -> None:
        """Clear all messages from history."""
        self._messages.clear()
        self._total_user_messages = 0
        self._total_assistant_messages = 0

    def truncate_to_length(self, max_length: int) -> None:
        """
        Truncate history to a maximum number of messages.

        Args:
            max_length: Maximum number of messages to keep
        """
        if len(self._messages) > max_length:
            self._messages = self._messages[-max_length:]

    def truncate_to_tokens(self, max_tokens: int) -> None:
        """
        Truncate history to approximate token count.

        Uses simple word count approximation: ~1.3 words per token.

        Args:
            max_tokens: Maximum approximate token count
        """
        total_tokens = 0
        keep_from_index = 0

        # Count from most recent backward
        for i in range(len(self._messages) - 1, -1, -1):
            msg = self._messages[i]
            # Approximate: 1.3 words per token
            words = len(msg.content.split())
            tokens = int(words * 1.3)

            if total_tokens + tokens > max_tokens:
                keep_from_index = i + 1
                break

            total_tokens += tokens

        if keep_from_index > 0:
            self._messages = self._messages[keep_from_index:]

    def _enforce_limits(self) -> None:
        """Enforce max_length and max_tokens limits."""
        # Enforce max length
        if self.max_length and len(self._messages) > self.max_length:
            self.truncate_to_length(self.max_length)

        # Enforce max tokens (approximate)
        if self.max_tokens:
            self.truncate_to_tokens(self.max_tokens)

    # -------------------------------------------------------------- #
    # Statistics
    # -------------------------------------------------------------- #

    def get_message_count(self) -> int:
        """Get total number of messages in history."""
        return len(self._messages)

    def get_total_user_messages(self) -> int:
        """Get total number of user messages (including truncated)."""
        return self._total_user_messages

    def get_total_assistant_messages(self) -> int:
        """Get total number of assistant messages (including truncated)."""
        return self._total_assistant_messages

    def get_approximate_token_count(self) -> int:
        """
        Get approximate total token count in current history.

        Uses simple approximation: 1.3 words per token.
        """
        total_words = sum(len(msg.content.split()) for msg in self._messages)
        return int(total_words * 1.3)

    def get_statistics(self) -> dict[str, any]:
        """Get conversation statistics."""
        return {
            "session_id": self.session_id,
            "current_message_count": len(self._messages),
            "total_user_messages": self._total_user_messages,
            "total_assistant_messages": self._total_assistant_messages,
            "approximate_tokens": self.get_approximate_token_count(),
            "max_length": self.max_length,
            "max_tokens": self.max_tokens,
        }

    # -------------------------------------------------------------- #
    # Export/Import
    # -------------------------------------------------------------- #

    def to_dict(self) -> dict:
        """Export conversation history to dict."""
        return {
            "session_id": self.session_id,
            "system_prompt": self.system_prompt,
            "max_length": self.max_length,
            "max_tokens": self.max_tokens,
            "total_user_messages": self._total_user_messages,
            "total_assistant_messages": self._total_assistant_messages,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "timestamp": msg.timestamp,
                    "metadata": msg.metadata,
                }
                for msg in self._messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConversationHistory:
        """Import conversation history from dict."""
        history = cls(
            session_id=data["session_id"],
            max_length=data.get("max_length", 50),
            max_tokens=data.get("max_tokens"),
            system_prompt=data.get("system_prompt"),
        )

        history._total_user_messages = data.get("total_user_messages", 0)
        history._total_assistant_messages = data.get("total_assistant_messages", 0)

        for msg_data in data.get("messages", []):
            msg = ConversationMessage(
                role=msg_data["role"],
                content=msg_data["content"],
                timestamp=msg_data.get("timestamp", 0),
                metadata=msg_data.get("metadata", {}),
            )
            history._messages.append(msg)

        return history

    # -------------------------------------------------------------- #
    # String Representation
    # -------------------------------------------------------------- #

    def __repr__(self) -> str:
        return (
            f"ConversationHistory(session_id={self.session_id!r}, "
            f"messages={len(self._messages)}, "
            f"tokens~{self.get_approximate_token_count()})"
        )

    def __len__(self) -> int:
        return len(self._messages)
