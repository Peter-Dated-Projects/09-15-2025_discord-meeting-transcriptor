"""
Conversation Service Layer.

This module provides the stateful conversation layer on top of the base
Ollama manager. It handles:

- Conversation and message persistence
- History management and truncation
- High-level chat API
- Metadata tracking (RAG context, tools, usage)
- LangChain integration

This is the main interface your application should use for multi-turn
conversations.

Usage:
    # Create conversation service
    conv_service = ConversationService(ollama_manager)

    # Start a chat
    response = await conv_service.chat(
        conversation_id="conv_123",
        user_input="Hello!",
        model="llama2"
    )

    # Continue conversation (history is automatic)
    response = await conv_service.chat(
        conversation_id="conv_123",
        user_input="Tell me more"
    )
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from source.services.ollama_request_manager.manager import (
        OllamaRequestManager,
    )
    from source.services.ollama_request_manager.models import (
        Conversation,
        Message,
        MessageChunk,
        MessageUsage,
    )


# -------------------------------------------------------------- #
# Conversation Message (for ConversationHistory)
# -------------------------------------------------------------- #


class ConversationMessage:
    """
    A simple message container for ConversationHistory.

    This is a lightweight alternative to the full Message model.
    """

    def __init__(
        self,
        role: Literal["system", "user", "assistant"],
        content: str,
        timestamp: float | None = None,
        metadata: dict | None = None,
    ):
        self.role = role
        self.content = content
        self.timestamp = timestamp or time.time()
        self.metadata = metadata or {}

    def to_dict(self) -> dict:
        """Convert to dictionary format."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


# -------------------------------------------------------------- #
# Conversation Service
# -------------------------------------------------------------- #


class ConversationService:
    """
    High-level conversation service with stateful chat management.

    This service provides:
    - Conversation lifecycle management
    - Message persistence and retrieval
    - Automatic history management
    - Single entrypoint chat() API
    - Metadata tracking for RAG, tools, etc.
    """

    def __init__(
        self,
        ollama_manager: OllamaRequestManager,
        max_history_messages: int = 50,
        max_history_tokens: int | None = None,
        default_system_prompt: str | None = None,
    ):
        """
        Initialize conversation service.

        Args:
            ollama_manager: Base Ollama request manager
            max_history_messages: Maximum messages to keep in history
            max_history_tokens: Maximum tokens in history (approximate)
            default_system_prompt: Default system prompt for conversations
        """
        self._ollama_manager = ollama_manager
        self._max_history_messages = max_history_messages
        self._max_history_tokens = max_history_tokens
        self._default_system_prompt = default_system_prompt

        # In-memory storage (replace with DB in production)
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, list[Message]] = {}  # conversation_id -> messages

    # -------------------------------------------------------------- #
    # Conversation Management
    # -------------------------------------------------------------- #

    def create_conversation(
        self,
        conversation_id: str | None = None,
        title: str | None = None,
        metadata: dict | None = None,
    ) -> Conversation:
        """
        Create a new conversation.

        Args:
            conversation_id: Optional conversation ID (generates UUID if not provided)
            title: Optional conversation title
            metadata: Optional metadata

        Returns:
            Created Conversation object
        """
        from source.services.ollama_request_manager.models import Conversation

        conversation = Conversation.create(title=title, metadata=metadata)

        # Use provided ID if given
        if conversation_id:
            conversation.id = conversation_id

        self._conversations[conversation.id] = conversation
        self._messages[conversation.id] = []

        return conversation

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Get a conversation by ID."""
        return self._conversations.get(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            if conversation_id in self._messages:
                del self._messages[conversation_id]
            return True
        return False

    def list_conversations(self, limit: int | None = None) -> list[Conversation]:
        """List all conversations, optionally limited."""
        conversations = list(self._conversations.values())
        conversations.sort(key=lambda c: c.updated_at, reverse=True)
        if limit:
            return conversations[:limit]
        return conversations

    def update_conversation_metadata(self, conversation_id: str, metadata: dict) -> bool:
        """Update conversation metadata."""
        conversation = self._conversations.get(conversation_id)
        if conversation:
            conversation.update_metadata(metadata)
            return True
        return False

    # -------------------------------------------------------------- #
    # Message Management
    # -------------------------------------------------------------- #

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        model: str | None = None,
        usage: MessageUsage | None = None,
        latency_ms: float | None = None,
        run_id: str | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> Message:
        """
        Append a message to a conversation.

        Args:
            conversation_id: Conversation ID
            role: Message role (user, assistant, system, tool)
            content: Message content
            model: Model that generated the message
            usage: Token usage information
            latency_ms: Latency in milliseconds
            run_id: LangChain run/trace ID
            parent_id: Parent message ID
            metadata: Additional metadata

        Returns:
            Created Message object
        """
        from source.services.ollama_request_manager.models import Message

        # Ensure conversation exists
        if conversation_id not in self._conversations:
            self.create_conversation(conversation_id=conversation_id)

        # Create message based on role
        if role == "user":
            message = Message.create_user_message(
                conversation_id=conversation_id,
                content=content,
                metadata=metadata,
                parent_id=parent_id,
            )
        elif role == "assistant":
            message = Message.create_assistant_message(
                conversation_id=conversation_id,
                content=content,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
                run_id=run_id,
                parent_id=parent_id,
                metadata=metadata,
            )
        elif role == "system":
            message = Message.create_system_message(
                conversation_id=conversation_id,
                content=content,
                metadata=metadata,
            )
        elif role == "tool":
            tool_name = metadata.get("tool_name", "unknown") if metadata else "unknown"
            tool_call_id = metadata.get("tool_call_id") if metadata else None
            message = Message.create_tool_message(
                conversation_id=conversation_id,
                content=content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                parent_id=parent_id,
                metadata=metadata,
            )
        else:
            raise ValueError(f"Invalid role: {role}")

        # Store message
        if conversation_id not in self._messages:
            self._messages[conversation_id] = []
        self._messages[conversation_id].append(message)

        # Update conversation stats
        conversation = self._conversations[conversation_id]
        conversation.message_count += 1
        if usage and usage.total_tokens:
            conversation.total_tokens += usage.total_tokens

        # Enforce history limits
        self._truncate_history(conversation_id)

        return message

    def get_history(
        self, conversation_id: str, limit: int | None = None, before_id: str | None = None
    ) -> list[Message]:
        """
        Get conversation history.

        Args:
            conversation_id: Conversation ID
            limit: Maximum number of messages to return
            before_id: Return messages before this message ID

        Returns:
            List of Message objects
        """
        messages = self._messages.get(conversation_id, [])

        # Filter by before_id if provided
        if before_id:
            before_index = next(
                (i for i, m in enumerate(messages) if m.id == before_id), len(messages)
            )
            messages = messages[:before_index]

        # Apply limit
        if limit:
            messages = messages[-limit:]

        return messages

    def get_message(self, conversation_id: str, message_id: str) -> Message | None:
        """Get a specific message by ID."""
        messages = self._messages.get(conversation_id, [])
        return next((m for m in messages if m.id == message_id), None)

    def update_message_metadata(
        self, conversation_id: str, message_id: str, metadata_update: dict
    ) -> bool:
        """
        Update metadata for a specific message.

        Args:
            conversation_id: Conversation ID
            message_id: Message ID
            metadata_update: Metadata fields to update

        Returns:
            True if message was found and updated
        """
        message = self.get_message(conversation_id, message_id)
        if message:
            message.metadata.update(metadata_update)
            return True
        return False

    def truncate_history(
        self,
        conversation_id: str,
        max_messages: int | None = None,
        max_tokens: int | None = None,
    ) -> int:
        """
        Manually truncate conversation history.

        Args:
            conversation_id: Conversation ID
            max_messages: Maximum messages to keep
            max_tokens: Maximum approximate tokens to keep

        Returns:
            Number of messages removed
        """
        messages = self._messages.get(conversation_id, [])
        original_count = len(messages)

        if max_messages:
            messages = messages[-max_messages:]

        if max_tokens:
            total_tokens = 0
            keep_from_index = 0

            # Count from most recent backward
            for i in range(len(messages) - 1, -1, -1):
                msg = messages[i]
                # Approximate: 1.3 words per token
                words = len(msg.content.split())
                tokens = int(words * 1.3)

                if total_tokens + tokens > max_tokens:
                    keep_from_index = i + 1
                    break

                total_tokens += tokens

            if keep_from_index > 0:
                messages = messages[keep_from_index:]

        self._messages[conversation_id] = messages
        return original_count - len(messages)

    def _truncate_history(self, conversation_id: str) -> None:
        """Internal method to enforce history limits."""
        self.truncate_history(
            conversation_id,
            max_messages=self._max_history_messages,
            max_tokens=self._max_history_tokens,
        )

    # -------------------------------------------------------------- #
    # High-Level Chat API
    # -------------------------------------------------------------- #

    async def chat(
        self,
        conversation_id: str,
        user_input: str,
        model: str | None = None,
        system_override: str | None = None,
        stream: bool = False,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_metadata: dict | None = None,
        rag_context: str | None = None,
        documents: list[str] | None = None,
        tools: list[dict] | None = None,
    ) -> Message | AsyncIterator[MessageChunk]:
        """
        High-level chat interface.

        This is the main entrypoint for conversational interactions.
        It handles:
        1. Creating user message
        2. Building full message history
        3. Calling base Ollama wrapper
        4. Creating assistant message with metadata
        5. Storing messages

        Args:
            conversation_id: Conversation ID
            user_input: User's message
            model: Model to use (optional override)
            system_override: System prompt override
            stream: Enable streaming
            temperature: Temperature override
            max_tokens: Max tokens override
            extra_metadata: Additional metadata to track
            rag_context: RAG context to include
            documents: Documents for RAG
            tools: Tool definitions

        Returns:
            Message object (or AsyncIterator if streaming)
        """
        from source.services.ollama_request_manager.models import MessageUsage

        start_time = time.time()

        # Ensure conversation exists
        if conversation_id not in self._conversations:
            self.create_conversation(conversation_id=conversation_id)

        # Create and store user message
        user_message = self.append_message(
            conversation_id=conversation_id,
            role="user",
            content=user_input,
            metadata=extra_metadata,
        )

        # Get conversation history
        history = self.get_history(conversation_id)

        # Build messages for Ollama
        messages = [msg.to_ollama_format() for msg in history]

        # Determine system prompt
        system_prompt = system_override or self._default_system_prompt

        # Build metadata for tracking
        request_metadata = {
            "conversation_id": conversation_id,
            "user_message_id": user_message.id,
            **(extra_metadata or {}),
        }

        # Add RAG context if provided
        if rag_context:
            request_metadata["rag_context"] = rag_context

        if documents:
            request_metadata["rag_documents_count"] = len(documents)

        try:
            # Call base Ollama manager
            if stream:
                return self._handle_streaming_response(
                    conversation_id=conversation_id,
                    model=model,
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    start_time=start_time,
                    request_metadata=request_metadata,
                    rag_context=rag_context,
                    documents=documents,
                    tools=tools,
                )
            else:
                result = await self._ollama_manager.query(
                    model=model,
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    num_predict=max_tokens,
                    stream=False,
                    metadata=request_metadata,
                    extra_context=rag_context,
                    documents=documents,
                    tools=tools,
                )

                # Calculate latency
                latency_ms = (time.time() - start_time) * 1000

                # Build usage info
                usage = None
                if result.eval_count or result.prompt_eval_count:
                    usage = MessageUsage(
                        prompt_tokens=result.prompt_eval_count,
                        completion_tokens=result.eval_count,
                        total_tokens=(result.prompt_eval_count or 0) + (result.eval_count or 0),
                    )

                # Build response metadata
                response_metadata = {
                    **(extra_metadata or {}),
                    "parent_message_id": user_message.id,
                }

                if rag_context or documents:
                    response_metadata["rag_enabled"] = True
                if tools:
                    response_metadata["tools_available"] = len(tools)

                # Create and store assistant message
                assistant_message = self.append_message(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=result.content,
                    model=result.model,
                    usage=usage,
                    latency_ms=latency_ms,
                    parent_id=user_message.id,
                    metadata=response_metadata,
                )

                return assistant_message

        except Exception as e:
            # Log error in user message metadata
            self.update_message_metadata(
                conversation_id,
                user_message.id,
                {"error": str(e), "error_type": type(e).__name__},
            )
            raise

    async def _handle_streaming_response(
        self,
        conversation_id: str,
        model: str | None,
        messages: list[dict],
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
        start_time: float,
        request_metadata: dict,
        rag_context: str | None,
        documents: list[str] | None,
        tools: list[dict] | None,
    ) -> AsyncIterator[MessageChunk]:
        """Handle streaming response from Ollama."""
        from source.services.ollama_request_manager.models import MessageChunk, MessageUsage

        full_content = ""
        message_id = None

        async for chunk in await self._ollama_manager.query(
            model=model,
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            num_predict=max_tokens,
            stream=True,
            metadata=request_metadata,
            extra_context=rag_context,
            documents=documents,
            tools=tools,
        ):
            full_content += chunk

            # Generate message ID on first chunk
            if message_id is None:
                import uuid

                message_id = str(uuid.uuid4())

            yield MessageChunk(
                conversation_id=conversation_id,
                message_id=message_id,
                content=chunk,
                done=False,
            )

        # Calculate latency
        latency_ms = (time.time() - start_time) * 1000

        # Approximate usage
        words = len(full_content.split())
        usage = MessageUsage(
            prompt_tokens=None,
            completion_tokens=int(words * 1.3),
            total_tokens=int(words * 1.3),
        )

        # Store final assistant message
        parent_id = request_metadata.get("user_message_id")
        response_metadata = {"parent_message_id": parent_id}

        if rag_context or documents:
            response_metadata["rag_enabled"] = True
        if tools:
            response_metadata["tools_available"] = len(tools)

        self.append_message(
            conversation_id=conversation_id,
            role="assistant",
            content=full_content,
            model=model,
            usage=usage,
            latency_ms=latency_ms,
            parent_id=parent_id,
            metadata=response_metadata,
        )

        # Yield final chunk
        yield MessageChunk(
            conversation_id=conversation_id, message_id=message_id, content="", done=True
        )

    # -------------------------------------------------------------- #
    # Utility Methods
    # -------------------------------------------------------------- #

    def get_statistics(self, conversation_id: str | None = None) -> dict[str, Any]:
        """Get service statistics."""
        if conversation_id:
            # Stats for specific conversation
            conversation = self._conversations.get(conversation_id)
            if not conversation:
                return {}

            messages = self._messages.get(conversation_id, [])
            return {
                "conversation_id": conversation_id,
                "message_count": len(messages),
                "total_tokens": conversation.total_tokens,
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
            }
        else:
            # Global stats
            return {
                "total_conversations": len(self._conversations),
                "total_messages": sum(len(msgs) for msgs in self._messages.values()),
                "total_tokens": sum(c.total_tokens for c in self._conversations.values()),
            }


# -------------------------------------------------------------- #
# Conversation History (Simple Alternative)
# -------------------------------------------------------------- #


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
        self,
        role: Literal["system", "user", "assistant"],
        content: str,
        metadata: dict | None = None,
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
        return [{"role": msg.role, "content": msg.content} for msg in self._messages[-n:]]

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

    def get_statistics(self) -> dict[str, Any]:
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
