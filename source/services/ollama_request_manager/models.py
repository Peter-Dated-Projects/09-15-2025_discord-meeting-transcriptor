"""
Message and Conversation Models.

This module defines the core data models for stateful conversations:
- Message: Individual messages with full metadata and observability
- Conversation: Conversation metadata and tracking
- MessageChunk: Streaming message chunks

These models support:
- Full LangChain integration
- RAG context tracking
- Tool/function calling metadata
- Observability (tokens, latency, tracing)
- Threading and parent-child relationships
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class MessageUsage:
    """Token usage information for a message."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class Message:
    """
    A single message in a conversation with full metadata.

    This is the universal message format that can be converted to/from:
    - LangChain BaseMessage
    - Ollama {role, content} format
    - Database records
    """

    id: str
    conversation_id: str
    role: Role
    content: str
    created_at: datetime

    # Who/what produced it
    model: str | None = None
    run_id: str | None = None  # LangChain run/trace ID
    parent_id: str | None = None  # For threading

    # Observability
    usage: MessageUsage | None = None
    latency_ms: float | None = None
    error: str | None = None

    # Metadata
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create_user_message(
        cls,
        conversation_id: str,
        content: str,
        metadata: dict | None = None,
        parent_id: str | None = None,
    ) -> Message:
        """Create a new user message."""
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="user",
            content=content,
            created_at=datetime.utcnow(),
            parent_id=parent_id,
            metadata=metadata or {},
        )

    @classmethod
    def create_assistant_message(
        cls,
        conversation_id: str,
        content: str,
        model: str | None = None,
        usage: MessageUsage | None = None,
        latency_ms: float | None = None,
        run_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> Message:
        """Create a new assistant message."""
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="assistant",
            content=content,
            created_at=datetime.utcnow(),
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            run_id=run_id,
            parent_id=parent_id,
            metadata=metadata or {},
        )

    @classmethod
    def create_system_message(
        cls,
        conversation_id: str,
        content: str,
        metadata: dict | None = None,
    ) -> Message:
        """Create a new system message."""
        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="system",
            content=content,
            created_at=datetime.utcnow(),
            metadata=metadata or {},
        )

    @classmethod
    def create_tool_message(
        cls,
        conversation_id: str,
        content: str,
        tool_name: str,
        tool_call_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> Message:
        """Create a new tool message."""
        metadata = metadata or {}
        metadata.update({"tool_name": tool_name, "tool_call_id": tool_call_id})

        return cls(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            role="tool",
            content=content,
            created_at=datetime.utcnow(),
            parent_id=parent_id,
            metadata=metadata,
        )

    def to_ollama_format(self) -> dict[str, str]:
        """Convert to Ollama message format."""
        return {"role": self.role, "content": self.content}

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
            "model": self.model,
            "run_id": self.run_id,
            "parent_id": self.parent_id,
            "usage": (
                {
                    "prompt_tokens": self.usage.prompt_tokens,
                    "completion_tokens": self.usage.completion_tokens,
                    "total_tokens": self.usage.total_tokens,
                }
                if self.usage
                else None
            ),
            "latency_ms": self.latency_ms,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Message:
        """Create Message from dictionary."""
        usage = None
        if data.get("usage"):
            usage = MessageUsage(
                prompt_tokens=data["usage"].get("prompt_tokens"),
                completion_tokens=data["usage"].get("completion_tokens"),
                total_tokens=data["usage"].get("total_tokens"),
            )

        return cls(
            id=data["id"],
            conversation_id=data["conversation_id"],
            role=data["role"],
            content=data["content"],
            created_at=datetime.fromisoformat(data["created_at"]),
            model=data.get("model"),
            run_id=data.get("run_id"),
            parent_id=data.get("parent_id"),
            usage=usage,
            latency_ms=data.get("latency_ms"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        return f"Message(id={self.id[:8]}..., role={self.role}, content={self.content[:50]}...)"


@dataclass
class Conversation:
    """
    Conversation metadata and tracking.

    Represents a multi-turn conversation session with metadata,
    timestamps, and optional title/description.
    """

    id: str
    created_at: datetime
    updated_at: datetime
    title: str | None = None
    metadata: dict = field(default_factory=dict)

    # Statistics
    message_count: int = 0
    total_tokens: int = 0

    @classmethod
    def create(cls, title: str | None = None, metadata: dict | None = None) -> Conversation:
        """Create a new conversation."""
        now = datetime.utcnow()
        return cls(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            title=title,
            metadata=metadata or {},
        )

    def update_metadata(self, updates: dict) -> None:
        """Update conversation metadata."""
        self.metadata.update(updates)
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "title": self.title,
            "metadata": self.metadata,
            "message_count": self.message_count,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Conversation:
        """Create Conversation from dictionary."""
        return cls(
            id=data["id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            title=data.get("title"),
            metadata=data.get("metadata", {}),
            message_count=data.get("message_count", 0),
            total_tokens=data.get("total_tokens", 0),
        )

    def __repr__(self) -> str:
        return (
            f"Conversation(id={self.id[:8]}..., title={self.title}, messages={self.message_count})"
        )


@dataclass
class MessageChunk:
    """
    A streaming chunk of a message.

    Used for real-time streaming responses.
    """

    conversation_id: str
    message_id: str
    content: str
    done: bool = False
    metadata: dict = field(default_factory=dict)
