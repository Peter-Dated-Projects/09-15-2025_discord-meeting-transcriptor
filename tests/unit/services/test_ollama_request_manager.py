"""
Unit tests for Ollama Request Manager.

Tests cover:
- Manager initialization and configuration
- Query interface (streaming and non-streaming)
- Session management
- Generation parameters
- Error handling and retries
- Statistics tracking
- Model management
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from source.services.ollama_request_manager.manager import (
    GenerationConfig,
    Message,
    OllamaQueryResult,
    OllamaRequestManager,
)

# -------------------------------------------------------------- #
# Fixtures
# -------------------------------------------------------------- #


@pytest.fixture
def mock_context():
    """Create a mock context."""
    context = MagicMock()
    context.workspace_path = "/mock/workspace"
    return context


@pytest.fixture
def mock_services():
    """Create a mock services manager with logging service."""
    services = MagicMock()
    services.logging_service = AsyncMock()
    services.logging_service.info = AsyncMock()
    services.logging_service.debug = AsyncMock()
    services.logging_service.warning = AsyncMock()
    services.logging_service.error = AsyncMock()
    return services


@pytest.fixture
def mock_ollama_client():
    """Create a mock Ollama async client."""
    with patch("source.services.ollama_request_manager.manager.ollama.AsyncClient") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client


@pytest.fixture
async def ollama_manager(mock_context, mock_ollama_client):  # noqa: ARG001
    """Create an OllamaRequestManager instance for testing."""
    manager = OllamaRequestManager(
        context=mock_context,
        host="http://localhost:11434",
        default_model="llama2",
        default_system_prompt="You are a helpful assistant",
        max_history_length=10,
        max_history_tokens=1000,
    )
    return manager


@pytest.fixture
async def started_manager(ollama_manager, mock_services):
    """Create a started manager with services."""
    await ollama_manager.on_start(mock_services)
    yield ollama_manager
    await ollama_manager.on_close()


# -------------------------------------------------------------- #
# Initialization Tests
# -------------------------------------------------------------- #


class TestInitialization:
    """Test manager initialization and configuration."""

    def test_init_with_defaults(self, mock_context, mock_ollama_client):  # noqa: ARG002
        """Test initialization with default parameters."""
        with patch.dict(
            "os.environ",
            {"OLLAMA_HOST": "localhost", "OLLAMA_PORT": "11434", "OLLAMA_MODEL": "llama2"},
        ):
            manager = OllamaRequestManager(context=mock_context)

            assert manager._default_model == "llama2"
            assert manager._host == "http://localhost:11434"
            assert manager._max_history_length == 50
            assert manager._max_history_tokens is None

    def test_init_with_custom_params(self, mock_context, mock_ollama_client):  # noqa: ARG002
        """Test initialization with custom parameters."""
        manager = OllamaRequestManager(
            context=mock_context,
            host="http://custom-host:8080",
            default_model="custom-model",
            default_system_prompt="Custom prompt",
            max_history_length=100,
            max_history_tokens=2000,
        )

        assert manager._host == "http://custom-host:8080"
        assert manager._default_model == "custom-model"
        assert manager._default_system_prompt == "Custom prompt"
        assert manager._max_history_length == 100
        assert manager._max_history_tokens == 2000

    def test_init_statistics(self, ollama_manager):
        """Test that statistics are initialized to zero."""
        assert ollama_manager._total_requests == 0
        assert ollama_manager._total_tokens_generated == 0
        assert ollama_manager._total_errors == 0
        assert ollama_manager._model_usage == {}

    async def test_on_start(self, ollama_manager, mock_services):
        """Test manager startup."""
        await ollama_manager.on_start(mock_services)

        assert ollama_manager.services == mock_services
        mock_services.logging_service.info.assert_called()

    async def test_on_close(self, started_manager):
        """Test manager shutdown."""
        # Add some sessions
        started_manager.create_session("session1")
        started_manager.create_session("session2")

        await started_manager.on_close()

        assert len(started_manager._sessions) == 0
        started_manager.services.logging_service.info.assert_called()


# -------------------------------------------------------------- #
# Query Interface Tests
# -------------------------------------------------------------- #


class TestQueryInterface:
    """Test the main query interface."""

    async def test_query_with_prompt_shortcut(self, started_manager):
        """Test query using prompt shortcut."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Hello there!"},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        result = await started_manager.query(prompt="Hello!")

        assert isinstance(result, OllamaQueryResult)
        assert result.content == "Hello there!"
        assert result.model == "llama2"
        assert result.done is True

    async def test_query_with_messages(self, started_manager):
        """Test query with explicit messages."""
        messages = [
            Message(role="user", content="What is Python?"),
            Message(role="assistant", content="Python is a programming language."),
            Message(role="user", content="Tell me more."),
        ]

        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Python is versatile..."},
                "model": "llama2",
                "done": True,
                "eval_count": 20,
            }
        )

        result = await started_manager.query(messages=messages)

        assert result.content == "Python is versatile..."
        assert started_manager._total_requests == 1

    async def test_query_with_dict_messages(self, started_manager):
        """Test query with dictionary-format messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "How can I help?"},
                "model": "llama2",
                "done": True,
                "eval_count": 5,
            }
        )

        result = await started_manager.query(messages=messages)

        assert result.content == "How can I help?"

    async def test_query_with_custom_parameters(self, started_manager):
        """Test query with custom generation parameters."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 15,
            }
        )

        _result = await started_manager.query(
            prompt="Test",
            temperature=0.9,
            top_p=0.95,
            top_k=50,
            num_predict=100,
            repeat_penalty=1.2,
            seed=42,
        )

        # Verify the call was made with correct options
        call_args = started_manager._client.chat.call_args
        options = call_args[1]["options"]

        assert options["temperature"] == 0.9
        assert options["top_p"] == 0.95
        assert options["top_k"] == 50
        assert options["num_predict"] == 100
        assert options["repeat_penalty"] == 1.2
        assert options["seed"] == 42

    async def test_query_with_json_format(self, started_manager):
        """Test query with JSON output format."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": '{"name": "John", "age": 30}'},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        result = await started_manager.query(prompt="Give me JSON", format="json")

        assert '{"name": "John", "age": 30}' in result.content

        # Verify format was passed
        call_args = started_manager._client.chat.call_args
        assert call_args[1]["format"] == "json"

    async def test_query_without_messages_or_session_raises(self, started_manager):
        """Test that query without messages or session_id raises error."""
        with pytest.raises(ValueError, match="Either messages or session_id must be provided"):
            await started_manager.query()

    async def test_query_with_system_prompt(self, started_manager):
        """Test query with custom system prompt."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 5,
            }
        )

        await started_manager.query(prompt="Test", system_prompt="You are a coding assistant")

        # Verify system prompt was added
        call_args = started_manager._client.chat.call_args
        messages = call_args[1]["messages"]

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a coding assistant"

    async def test_query_uses_default_system_prompt(self, started_manager):
        """Test that default system prompt is used when no override."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 5,
            }
        )

        await started_manager.query(prompt="Test")

        # Verify default system prompt was added
        call_args = started_manager._client.chat.call_args
        messages = call_args[1]["messages"]

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant"


# -------------------------------------------------------------- #
# Streaming Tests
# -------------------------------------------------------------- #


class TestStreaming:
    """Test streaming functionality."""

    async def test_query_streaming(self, started_manager):
        """Test streaming query."""

        async def mock_stream():
            chunks = [
                {"message": {"content": "Hello "}},
                {"message": {"content": "world"}},
                {"message": {"content": "!"}},
            ]
            for chunk in chunks:
                yield chunk

        started_manager._client.chat = AsyncMock(return_value=mock_stream())

        result = await started_manager.query(prompt="Test", stream=True)

        chunks = []
        async for chunk in result:
            chunks.append(chunk)

        assert chunks == ["Hello ", "world", "!"]
        assert started_manager._total_requests == 1

    async def test_streaming_updates_token_count(self, started_manager):
        """Test that streaming updates token count (approximation)."""

        async def mock_stream():
            yield {"message": {"content": "This is a test response with multiple words"}}

        started_manager._client.chat = AsyncMock(return_value=mock_stream())

        result = await started_manager.query(prompt="Test", stream=True)

        async for _ in result:
            pass

        # Should have approximate token count from word count
        assert started_manager._total_tokens_generated > 0


# -------------------------------------------------------------- #
# Session Management Tests
# -------------------------------------------------------------- #


class TestSessionManagement:
    """Test session management functionality."""

    def test_create_session(self, ollama_manager):
        """Test creating a new session."""
        session = ollama_manager.create_session("test_session")

        assert session.session_id == "test_session"
        assert "test_session" in ollama_manager._sessions

    def test_create_duplicate_session_raises(self, ollama_manager):
        """Test that creating duplicate session raises error."""
        ollama_manager.create_session("test_session")

        with pytest.raises(ValueError, match="already exists"):
            ollama_manager.create_session("test_session")

    def test_get_session(self, ollama_manager):
        """Test getting an existing session."""
        created = ollama_manager.create_session("test_session")
        retrieved = ollama_manager.get_session("test_session")

        assert created == retrieved

    def test_get_nonexistent_session(self, ollama_manager):
        """Test getting a session that doesn't exist."""
        result = ollama_manager.get_session("nonexistent")

        assert result is None

    def test_delete_session(self, ollama_manager):
        """Test deleting a session."""
        ollama_manager.create_session("test_session")
        result = ollama_manager.delete_session("test_session")

        assert result is True
        assert "test_session" not in ollama_manager._sessions

    def test_delete_nonexistent_session(self, ollama_manager):
        """Test deleting a session that doesn't exist."""
        result = ollama_manager.delete_session("nonexistent")

        assert result is False

    def test_clear_all_sessions(self, ollama_manager):
        """Test clearing all sessions."""
        ollama_manager.create_session("session1")
        ollama_manager.create_session("session2")
        ollama_manager.create_session("session3")

        ollama_manager.clear_all_sessions()

        assert len(ollama_manager._sessions) == 0

    async def test_query_with_session_id(self, started_manager):
        """Test query with session_id creates and uses session."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 5,
            }
        )

        # First query
        await started_manager.query(prompt="First message", session_id="test_session")

        # Verify session was created
        assert "test_session" in started_manager._sessions
        session = started_manager.get_session("test_session")
        assert session.get_message_count() > 0

    async def test_session_maintains_history(self, started_manager):
        """Test that session maintains conversation history."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 5,
            }
        )

        # Multiple queries in same session
        await started_manager.query(prompt="Message 1", session_id="test_session")
        await started_manager.query(prompt="Message 2", session_id="test_session")
        await started_manager.query(prompt="Message 3", session_id="test_session")

        session = started_manager.get_session("test_session")

        # Should have 3 user messages + 3 assistant responses
        assert session.get_message_count() == 6


# -------------------------------------------------------------- #
# RAG Context Tests
# -------------------------------------------------------------- #


class TestRAGContext:
    """Test RAG context and document handling."""

    async def test_query_with_extra_context(self, started_manager):
        """Test query with extra context."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response based on context"},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        await started_manager.query(
            prompt="What is the company name?", extra_context="The company name is Acme Corp."
        )

        # Verify context was inserted
        call_args = started_manager._client.chat.call_args
        messages = call_args[1]["messages"]

        # Should have system prompt, context, and user message
        context_found = any("Context:" in msg["content"] for msg in messages)
        assert context_found

    async def test_query_with_documents(self, started_manager):
        """Test query with document list."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response based on documents"},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        documents = [
            "Document 1 content",
            "Document 2 content",
            "Document 3 content",
        ]

        await started_manager.query(prompt="Summarize the documents", documents=documents)

        # Verify documents were included
        call_args = started_manager._client.chat.call_args
        messages = call_args[1]["messages"]

        context_found = any("Context:" in msg["content"] for msg in messages)
        assert context_found

    async def test_query_with_both_context_and_documents(self, started_manager):
        """Test query with both extra context and documents."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        await started_manager.query(
            prompt="Question", extra_context="Additional context", documents=["Doc 1", "Doc 2"]
        )

        # Verify both were included
        call_args = started_manager._client.chat.call_args
        messages = call_args[1]["messages"]

        context_msg = next(msg for msg in messages if "Context:" in msg["content"])
        assert "Additional context" in context_msg["content"]
        assert "Doc 1" in context_msg["content"]
        assert "Doc 2" in context_msg["content"]


# -------------------------------------------------------------- #
# Error Handling and Retry Tests
# -------------------------------------------------------------- #


class TestErrorHandling:
    """Test error handling and retry logic."""

    async def test_retry_on_timeout(self, started_manager):
        """Test that timeouts trigger retries."""
        # First two calls timeout, third succeeds
        started_manager._client.chat = AsyncMock(
            side_effect=[
                asyncio.TimeoutError(),
                asyncio.TimeoutError(),
                {
                    "message": {"content": "Success"},
                    "model": "llama2",
                    "done": True,
                    "eval_count": 5,
                },
            ]
        )

        result = await started_manager.query(
            prompt="Test", max_retries=3, retry_backoff=0.01  # Fast backoff for testing
        )

        assert result.content == "Success"
        assert started_manager._client.chat.call_count == 3

    async def test_retry_on_exception(self, started_manager):
        """Test that exceptions trigger retries."""
        # First call fails, second succeeds
        started_manager._client.chat = AsyncMock(
            side_effect=[
                Exception("Network error"),
                {
                    "message": {"content": "Success"},
                    "model": "llama2",
                    "done": True,
                    "eval_count": 5,
                },
            ]
        )

        result = await started_manager.query(prompt="Test", max_retries=2, retry_backoff=0.01)

        assert result.content == "Success"

    async def test_all_retries_exhausted(self, started_manager):
        """Test that RuntimeError is raised after all retries fail."""
        started_manager._client.chat = AsyncMock(side_effect=Exception("Persistent error"))

        with pytest.raises(RuntimeError, match="failed after .* attempts"):
            await started_manager.query(prompt="Test", max_retries=3, retry_backoff=0.01)

        assert started_manager._total_errors == 1

    async def test_streaming_error_handling(self, started_manager):
        """Test error handling in streaming mode."""
        started_manager._client.chat = AsyncMock(side_effect=Exception("Streaming error"))

        result = await started_manager.query(prompt="Test", stream=True)

        with pytest.raises(Exception, match="Streaming error"):
            async for _ in result:
                pass

        assert started_manager._total_errors == 1


# -------------------------------------------------------------- #
# Statistics Tests
# -------------------------------------------------------------- #


class TestStatistics:
    """Test statistics tracking."""

    async def test_statistics_initialization(self, ollama_manager):
        """Test that statistics start at zero."""
        stats = ollama_manager.get_statistics()

        assert stats["total_requests"] == 0
        assert stats["total_tokens_generated"] == 0
        assert stats["total_errors"] == 0
        assert stats["model_usage"] == {}
        assert stats["active_sessions"] == 0

    async def test_statistics_track_requests(self, started_manager):
        """Test that requests are tracked."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        await started_manager.query(prompt="Test 1")
        await started_manager.query(prompt="Test 2")
        await started_manager.query(prompt="Test 3")

        stats = started_manager.get_statistics()
        assert stats["total_requests"] == 3

    async def test_statistics_track_tokens(self, started_manager):
        """Test that tokens are tracked."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 25,
            }
        )

        await started_manager.query(prompt="Test 1")
        await started_manager.query(prompt="Test 2")

        stats = started_manager.get_statistics()
        assert stats["total_tokens_generated"] == 50  # 25 * 2

    async def test_statistics_track_model_usage(self, started_manager):
        """Test that per-model usage is tracked."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        await started_manager.query(prompt="Test", model="llama2")
        await started_manager.query(prompt="Test", model="llama2")
        await started_manager.query(prompt="Test", model="codellama")

        stats = started_manager.get_statistics()
        assert stats["model_usage"]["llama2"] == 2
        assert stats["model_usage"]["codellama"] == 1

    async def test_statistics_track_active_sessions(self, ollama_manager):
        """Test that active sessions are tracked."""
        ollama_manager.create_session("session1")
        ollama_manager.create_session("session2")
        ollama_manager.create_session("session3")

        stats = ollama_manager.get_statistics()
        assert stats["active_sessions"] == 3

        ollama_manager.delete_session("session1")

        stats = ollama_manager.get_statistics()
        assert stats["active_sessions"] == 2


# -------------------------------------------------------------- #
# Model Management Tests
# -------------------------------------------------------------- #


class TestModelManagement:
    """Test model listing and pulling."""

    async def test_list_models_success(self, started_manager):
        """Test listing available models."""
        started_manager._client.list = AsyncMock(
            return_value={
                "models": [
                    {"name": "llama2", "size": 1000000},
                    {"name": "codellama", "size": 2000000},
                ]
            }
        )

        models = await started_manager.list_models()

        assert len(models) == 2
        assert models[0]["name"] == "llama2"
        assert models[1]["name"] == "codellama"

    async def test_list_models_error(self, started_manager):
        """Test error handling when listing models."""
        started_manager._client.list = AsyncMock(side_effect=Exception("Connection error"))

        models = await started_manager.list_models()

        assert models == []
        started_manager.services.logging_service.error.assert_called()

    async def test_pull_model_success(self, started_manager):
        """Test pulling a model."""
        started_manager._client.pull = AsyncMock()

        result = await started_manager.pull_model("llama2:13b")

        assert result is True
        started_manager._client.pull.assert_called_once_with("llama2:13b")
        started_manager.services.logging_service.info.assert_called()

    async def test_pull_model_error(self, started_manager):
        """Test error handling when pulling a model."""
        started_manager._client.pull = AsyncMock(side_effect=Exception("Network error"))

        result = await started_manager.pull_model("invalid-model")

        assert result is False
        started_manager.services.logging_service.error.assert_called()


# -------------------------------------------------------------- #
# Data Model Tests
# -------------------------------------------------------------- #


class TestDataModels:
    """Test data model classes."""

    def test_message_creation(self):
        """Test Message creation."""
        msg = Message(role="user", content="Hello")

        assert msg.role == "user"
        assert msg.content == "Hello"

    def test_generation_config_defaults(self):
        """Test GenerationConfig defaults."""
        config = GenerationConfig()

        assert config.temperature == 0.7
        assert config.top_p == 0.9
        assert config.top_k == 40
        assert config.repeat_penalty == 1.1
        assert config.num_predict is None
        assert config.seed is None
        assert config.stop == []

    def test_generation_config_custom(self):
        """Test GenerationConfig with custom values."""
        config = GenerationConfig(
            temperature=0.9,
            top_p=0.95,
            top_k=50,
            num_predict=100,
            stop=["END"],
            repeat_penalty=1.2,
            seed=42,
        )

        assert config.temperature == 0.9
        assert config.top_p == 0.95
        assert config.top_k == 50
        assert config.num_predict == 100
        assert config.stop == ["END"]
        assert config.repeat_penalty == 1.2
        assert config.seed == 42

    def test_ollama_query_result(self):
        """Test OllamaQueryResult creation."""
        result = OllamaQueryResult(
            content="Test response",
            model="llama2",
            done=True,
            eval_count=25,
            total_duration=1000000,
        )

        assert result.content == "Test response"
        assert result.model == "llama2"
        assert result.done is True
        assert result.eval_count == 25
        assert result.total_duration == 1000000


# -------------------------------------------------------------- #
# Integration-Style Tests
# -------------------------------------------------------------- #


class TestIntegration:
    """Integration-style tests for complete workflows."""

    async def test_complete_conversation_flow(self, started_manager):
        """Test a complete multi-turn conversation."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "Response"},
                "model": "llama2",
                "done": True,
                "eval_count": 10,
            }
        )

        session_id = "conversation_test"

        # Turn 1
        result1 = await started_manager.query(prompt="Hello", session_id=session_id)
        assert result1.content == "Response"

        # Turn 2
        result2 = await started_manager.query(prompt="How are you?", session_id=session_id)
        assert result2.content == "Response"

        # Turn 3
        result3 = await started_manager.query(prompt="Goodbye", session_id=session_id)
        assert result3.content == "Response"

        # Verify session
        session = started_manager.get_session(session_id)
        assert session.get_message_count() == 6  # 3 user + 3 assistant

        # Verify statistics
        stats = started_manager.get_statistics()
        assert stats["total_requests"] == 3
        assert stats["active_sessions"] == 1

    async def test_rag_workflow(self, started_manager):
        """Test RAG-style workflow with context."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": "The company was founded in 2020."},
                "model": "llama2",
                "done": True,
                "eval_count": 15,
            }
        )

        documents = [
            "Company history: Founded in 2020 by Jane Smith.",
            "Products: AI-powered chatbot.",
            "Team: 50 employees across 3 offices.",
        ]

        result = await started_manager.query(
            prompt="When was the company founded?",
            documents=documents,
            temperature=0.2,  # Lower for factual queries
        )

        assert "2020" in result.content

    async def test_json_output_workflow(self, started_manager):
        """Test JSON output workflow."""
        started_manager._client.chat = AsyncMock(
            return_value={
                "message": {"content": '{"status": "success", "data": {"id": 123}}'},
                "model": "llama2",
                "done": True,
                "eval_count": 20,
            }
        )

        result = await started_manager.query(prompt="Return a JSON object", format="json")

        import json

        data = json.loads(result.content)
        assert data["status"] == "success"
        assert data["data"]["id"] == 123
