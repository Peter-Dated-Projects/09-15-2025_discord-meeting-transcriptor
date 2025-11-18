"""
Ollama Request Manager Service.

This module provides a comprehensive wrapper around the Ollama API with:
- Full chat history management
- Configurable generation parameters
- Streaming and non-streaming support
- Session/conversation tracking
- Retry logic with exponential backoff
- JSON output mode support

Example usage:
    from source.services.ollama_request_manager import OllamaRequestManager

    # Initialize manager
    manager = OllamaRequestManager(context, host="http://localhost:11434")
    await manager.on_start(services)

    # Simple query
    result = await manager.query(
        model="llama2",
        prompt="What is the capital of France?"
    )
    print(result.content)

    # Session-based conversation
    result = await manager.query(
        model="llama2",
        prompt="Tell me about Python",
        session_id="user_123"
    )
    result = await manager.query(
        model="llama2",
        prompt="What are its main features?",
        session_id="user_123"
    )

    # Streaming
    async for chunk in await manager.query(
        model="llama2",
        prompt="Tell me a long story",
        stream=True
    ):
        print(chunk, end="")
"""

from source.services.ollama_request_manager.conversation import (
    ConversationHistory,
    ConversationMessage,
)
from source.services.ollama_request_manager.manager import (
    GenerationConfig,
    Message,
    OllamaQueryInput,
    OllamaQueryResult,
    OllamaRequestManager,
)

__all__ = [
    "OllamaRequestManager",
    "OllamaQueryInput",
    "OllamaQueryResult",
    "GenerationConfig",
    "Message",
    "ConversationHistory",
    "ConversationMessage",
]
