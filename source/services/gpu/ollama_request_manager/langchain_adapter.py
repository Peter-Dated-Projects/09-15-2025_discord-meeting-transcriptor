"""
LangChain Integration Adapters.

This module provides adapters between our Message model and LangChain's
BaseMessage types, enabling seamless integration with LangChain chains,
agents, and tools.

Supports:
- Message <-> BaseMessage conversion
- AIMessage, HumanMessage, SystemMessage, ToolMessage
- Metadata preservation
- Usage tracking
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.services.ollama_request_manager.models import Message, MessageUsage

# LangChain imports (optional dependency)
try:
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False

    # Create dummy types for type checking
    class BaseMessage:  # type: ignore
        pass

    AIMessage = BaseMessage  # type: ignore
    HumanMessage = BaseMessage  # type: ignore
    SystemMessage = BaseMessage  # type: ignore
    ToolMessage = BaseMessage  # type: ignore


class LangChainAdapter:
    """
    Adapter for converting between Message and LangChain BaseMessage.

    This enables seamless integration with LangChain chains, agents,
    and other LangChain components while maintaining our own Message
    format for storage and observability.
    """

    @staticmethod
    def to_langchain_messages(messages: list[Message]) -> list[BaseMessage]:
        """
        Convert a list of Messages to LangChain BaseMessage format.

        Args:
            messages: List of our Message objects

        Returns:
            List of LangChain BaseMessage objects

        Raises:
            ImportError: If LangChain is not installed
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LangChain is not installed. Install with: pip install langchain-core"
            )

        lc_messages = []
        for msg in messages:
            lc_msg = LangChainAdapter.message_to_langchain(msg)
            lc_messages.append(lc_msg)

        return lc_messages

    @staticmethod
    def message_to_langchain(message: Message) -> BaseMessage:
        """
        Convert a single Message to LangChain BaseMessage.

        Args:
            message: Our Message object

        Returns:
            LangChain BaseMessage object

        Raises:
            ImportError: If LangChain is not installed
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LangChain is not installed. Install with: pip install langchain-core"
            )

        # Build additional kwargs for metadata
        additional_kwargs = {}
        if message.metadata:
            additional_kwargs.update(message.metadata)

        # Convert based on role
        if message.role == "user":
            return HumanMessage(content=message.content, additional_kwargs=additional_kwargs)
        elif message.role == "assistant":
            return AIMessage(content=message.content, additional_kwargs=additional_kwargs)
        elif message.role == "system":
            return SystemMessage(content=message.content, additional_kwargs=additional_kwargs)
        elif message.role == "tool":
            tool_call_id = message.metadata.get("tool_call_id", "")
            return ToolMessage(
                content=message.content,
                tool_call_id=tool_call_id,
                additional_kwargs=additional_kwargs,
            )
        else:
            # Default to HumanMessage for unknown roles
            return HumanMessage(content=message.content, additional_kwargs=additional_kwargs)

    @staticmethod
    def from_langchain_message(
        lc_message: BaseMessage,
        conversation_id: str,
        model: str | None = None,
        usage: MessageUsage | None = None,
        latency_ms: float | None = None,
        run_id: str | None = None,
        parent_id: str | None = None,
    ) -> Message:
        """
        Convert a LangChain BaseMessage to our Message format.

        Args:
            lc_message: LangChain BaseMessage object
            conversation_id: Conversation ID for the message
            model: Model that generated the message
            usage: Token usage information
            latency_ms: Latency in milliseconds
            run_id: LangChain run/trace ID
            parent_id: Parent message ID

        Returns:
            Our Message object

        Raises:
            ImportError: If LangChain is not installed
        """
        if not LANGCHAIN_AVAILABLE:
            raise ImportError(
                "LangChain is not installed. Install with: pip install langchain-core"
            )

        from source.services.ollama_request_manager.models import Message

        # Determine role from message type
        if isinstance(lc_message, HumanMessage):
            role = "user"
        elif isinstance(lc_message, AIMessage):
            role = "assistant"
        elif isinstance(lc_message, SystemMessage):
            role = "system"
        elif isinstance(lc_message, ToolMessage):
            role = "tool"
        else:
            role = "user"  # Default fallback

        # Extract metadata from additional_kwargs
        metadata = {}
        if hasattr(lc_message, "additional_kwargs"):
            metadata.update(lc_message.additional_kwargs)

        # Create appropriate message type
        if role == "user":
            return Message.create_user_message(
                conversation_id=conversation_id,
                content=lc_message.content,
                metadata=metadata,
                parent_id=parent_id,
            )
        elif role == "assistant":
            return Message.create_assistant_message(
                conversation_id=conversation_id,
                content=lc_message.content,
                model=model,
                usage=usage,
                latency_ms=latency_ms,
                run_id=run_id,
                parent_id=parent_id,
                metadata=metadata,
            )
        elif role == "system":
            return Message.create_system_message(
                conversation_id=conversation_id, content=lc_message.content, metadata=metadata
            )
        elif role == "tool":
            tool_call_id = metadata.get("tool_call_id")
            tool_name = metadata.get("tool_name", "unknown")
            return Message.create_tool_message(
                conversation_id=conversation_id,
                content=lc_message.content,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                parent_id=parent_id,
                metadata=metadata,
            )
        else:
            # Fallback
            return Message.create_user_message(
                conversation_id=conversation_id,
                content=lc_message.content,
                metadata=metadata,
                parent_id=parent_id,
            )

    @staticmethod
    def is_available() -> bool:
        """Check if LangChain is available."""
        return LANGCHAIN_AVAILABLE
