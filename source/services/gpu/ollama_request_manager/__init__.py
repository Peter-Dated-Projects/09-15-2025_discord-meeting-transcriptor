"""
Ollama Request Manager Service.

This module provides a comprehensive wrapper around the Ollama API with:
- Stateless base Ollama wrapper (manager.py)
- Stateful conversation service (conversation.py)
- Full chat history management
- Configurable generation parameters
- Streaming and non-streaming support
- LangChain integration
- Retry logic with exponential backoff
- JSON output mode support

Example usage (base manager):
    from source.services.ollama_request_manager import OllamaRequestManager

    # Initialize manager
    manager = OllamaRequestManager(context)
    await manager.on_start(services)

    # Simple query
    result = await manager.query(
        model="llama2",
        prompt="What is the capital of France?"
    )
    print(result.content)

Example usage (conversation service):
    from source.services.ollama_request_manager import (
        OllamaRequestManager,
        ConversationService
    )

    # Initialize
    manager = OllamaRequestManager(context)
    await manager.on_start(services)

    conv_service = ConversationService(manager)

    # Start a conversation
    response = await conv_service.chat(
        conversation_id="user_123",
        user_input="Tell me about Python"
    )

    # Continue (history is automatic)
    response = await conv_service.chat(
        conversation_id="user_123",
        user_input="What are its main features?"
    )
"""

from source.services.gpu.ollama_request_manager.conversation import ConversationService
from source.services.gpu.ollama_request_manager.langchain_adapter import LangChainAdapter
from source.services.gpu.ollama_request_manager.manager import (
    GenerationConfig,
)
from source.services.gpu.ollama_request_manager.manager import Message as OllamaMessage
from source.services.gpu.ollama_request_manager.manager import (
    OllamaQueryInput,
    OllamaQueryResult,
    OllamaRequestManager,
)
from source.services.gpu.ollama_request_manager.models import (
    Conversation,
    Document,
    DocumentCollection,
    DocumentType,
    Message,
    MessageChunk,
    MessageUsage,
)

__all__ = [
    # Base manager
    "OllamaRequestManager",
    "OllamaQueryInput",
    "OllamaQueryResult",
    "GenerationConfig",
    "OllamaMessage",
    # Conversation service
    "ConversationService",
    # Document management
    "Document",
    "DocumentCollection",
    "DocumentType",
    # Models
    "Message",
    "MessageUsage",
    "MessageChunk",
    "Conversation",
    # LangChain integration
    "LangChainAdapter",
]
