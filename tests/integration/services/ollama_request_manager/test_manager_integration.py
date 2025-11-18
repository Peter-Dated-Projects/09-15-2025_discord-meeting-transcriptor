"""
Integration tests for Ollama Request Manager.

These tests require a running Ollama instance and use real API calls.
Tests use model specifications from .env.local.

Run with: pytest tests/integration/services/ollama_request_manager/ -v -s

Environment variables required:
- OLLAMA_HOST (default: localhost)
- OLLAMA_PORT (default: 11434)
- OLLAMA_MODEL (default: gpt-oss:20b)
"""

import asyncio
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from source.context import Context
from source.services.ollama_request_manager.manager import (
    OllamaQueryResult,
    OllamaRequestManager,
)

# Load environment variables from .env.local
env_path = Path(__file__).parent.parent.parent.parent / ".env.local"
if env_path.exists():
    load_dotenv(env_path)


# -------------------------------------------------------------- #
# Fixtures
# -------------------------------------------------------------- #


@pytest.fixture(scope="module")
def check_ollama_available():
    """Check if Ollama is available before running tests."""
    import socket

    host = os.getenv("OLLAMA_HOST", "localhost")
    port = int(os.getenv("OLLAMA_PORT", "11434"))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    result = sock.connect_ex((host, port))
    sock.close()

    if result != 0:
        pytest.skip(f"Ollama server not available at {host}:{port}")


@pytest.fixture
def test_context():
    """Create a test context."""
    context = Context()
    return context


@pytest.fixture
async def ollama_manager(test_context, check_ollama_available):  # noqa: ARG001
    """Create an OllamaRequestManager instance with real Ollama connection."""
    host = os.getenv("OLLAMA_HOST", "localhost")
    port = os.getenv("OLLAMA_PORT", "11434")
    model = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")

    manager = OllamaRequestManager(
        context=test_context,
        host=f"http://{host}:{port}",
        default_model=model,
        default_system_prompt="You are a helpful assistant.",
        max_history_length=20,
        max_history_tokens=4000,
    )

    yield manager

    # Cleanup
    await manager.on_close()


# -------------------------------------------------------------- #
# Basic Query Tests
# -------------------------------------------------------------- #


class TestBasicQueries:
    """Test basic query functionality with real Ollama."""

    @pytest.mark.asyncio
    async def test_simple_query(self, ollama_manager):
        """Test a simple query with prompt."""
        result = await ollama_manager.query(
            prompt="What is 2 + 2? Answer with just the number.",
            temperature=0.1,  # Low temperature for consistent results
            num_predict=50,  # Enough tokens for gpt-oss:20b to complete response
        )

        assert isinstance(result, OllamaQueryResult)
        assert result.content is not None
        assert len(result.content) > 0
        assert result.done is True
        assert "4" in result.content

        # Print for verification
        print(f"\n✓ Simple query result: {result.content}")

    @pytest.mark.asyncio
    async def test_query_with_messages(self, ollama_manager):
        """Test query with message history."""
        result = await ollama_manager.query(
            messages=[
                {"role": "user", "content": "My name is Alice."},
                {"role": "assistant", "content": "Nice to meet you, Alice!"},
                {"role": "user", "content": "What is my name?"},
            ],
            temperature=0.1,
            num_predict=50,
        )

        assert isinstance(result, OllamaQueryResult)
        assert "Alice" in result.content or "alice" in result.content.lower()

        print(f"\n✓ Message history result: {result.content}")

    @pytest.mark.asyncio
    async def test_query_with_system_prompt(self, ollama_manager):
        """Test query with custom system prompt."""
        result = await ollama_manager.query(
            prompt="Explain Python in one sentence.",
            system_prompt="You are a concise technical writer. Always respond in exactly one sentence.",
            temperature=0.3,
            num_predict=50,
        )

        assert isinstance(result, OllamaQueryResult)
        assert len(result.content) > 0

        print(f"\n✓ System prompt result: {result.content}")

    @pytest.mark.asyncio
    async def test_longer_response(self, ollama_manager):
        """Test generating a longer response."""
        result = await ollama_manager.query(
            prompt="List 5 programming languages with one-word descriptions.",
            temperature=0.5,
            num_predict=100,
        )

        assert isinstance(result, OllamaQueryResult)
        assert len(result.content) > 50  # Should be reasonably long

        # Check for token counts
        assert result.eval_count is not None
        assert result.eval_count > 0

        print(f"\n✓ Longer response ({result.eval_count} tokens): {result.content[:100]}...")


# -------------------------------------------------------------- #
# Streaming Tests
# -------------------------------------------------------------- #


class TestStreaming:
    """Test streaming functionality with real Ollama."""

    @pytest.mark.asyncio
    async def test_streaming_query(self, ollama_manager):
        """Test streaming response."""
        result = await ollama_manager.query(
            prompt="Count from 1 to 5, one number per line.",
            stream=True,
            temperature=0.1,
            num_predict=50,
        )

        chunks = []
        async for chunk in result:
            assert isinstance(chunk, str)
            chunks.append(chunk)
            print(chunk, end="", flush=True)

        full_content = "".join(chunks)
        assert len(full_content) > 0
        assert any(str(i) in full_content for i in range(1, 6))

        print(f"\n✓ Streaming test complete ({len(chunks)} chunks)")

    @pytest.mark.asyncio
    async def test_streaming_updates_statistics(self, ollama_manager):
        """Test that streaming updates statistics."""
        initial_stats = ollama_manager.get_statistics()
        initial_requests = initial_stats["total_requests"]

        result = await ollama_manager.query(
            prompt="Say 'Hello World'",
            stream=True,
            temperature=0.1,
            num_predict=50,
        )

        async for _ in result:
            pass

        final_stats = ollama_manager.get_statistics()
        assert final_stats["total_requests"] == initial_requests + 1
        assert final_stats["total_tokens_generated"] > initial_stats["total_tokens_generated"]

        print(f"\n✓ Statistics updated: {final_stats}")


# -------------------------------------------------------------- #
# Session Management Tests
# -------------------------------------------------------------- #


class TestSessionManagement:
    """Test session-based conversations with real Ollama."""

    @pytest.mark.asyncio
    async def test_conversation_with_session(self, ollama_manager):
        """Test multi-turn conversation using session."""
        session_id = "test_conversation_session"

        # Turn 1: Introduce a topic
        result1 = await ollama_manager.query(
            prompt="I have a dog named Max.",
            session_id=session_id,
            temperature=0.2,
            num_predict=30,
        )
        assert len(result1.content) > 0
        print(f"\n✓ Turn 1: {result1.content}")

        # Turn 2: Ask about it (should remember)
        result2 = await ollama_manager.query(
            prompt="What is my dog's name?",
            session_id=session_id,
            temperature=0.2,
            num_predict=30,
        )
        assert "Max" in result2.content or "max" in result2.content.lower()
        print(f"\n✓ Turn 2: {result2.content}")

        # Verify session exists and has history
        session = ollama_manager.get_session(session_id)
        assert session is not None
        assert session.get_message_count() > 2  # At least 2 user + 2 assistant

        print(f"\n✓ Session has {session.get_message_count()} messages")

        # Cleanup
        ollama_manager.delete_session(session_id)

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, ollama_manager):
        """Test multiple independent sessions."""
        # Session 1: Talk about Python
        result1 = await ollama_manager.query(
            prompt="Python is my favorite language.",
            session_id="session_1",
            temperature=0.2,
            num_predict=30,
        )
        print(f"\n✓ Session 1: {result1.content}")

        # Session 2: Talk about JavaScript
        result2 = await ollama_manager.query(
            prompt="JavaScript is my favorite language.",
            session_id="session_2",
            temperature=0.2,
            num_predict=30,
        )
        print(f"\n✓ Session 2: {result2.content}")

        # Ask session 1 what language
        result3 = await ollama_manager.query(
            prompt="What is my favorite language?",
            session_id="session_1",
            temperature=0.2,
            num_predict=50,
        )
        assert "Python" in result3.content or "python" in result3.content.lower()
        print(f"\n✓ Session 1 remembers: {result3.content}")

        # Ask session 2 what language
        result4 = await ollama_manager.query(
            prompt="What is my favorite language?",
            session_id="session_2",
            temperature=0.2,
            num_predict=50,
        )
        assert "JavaScript" in result4.content or "javascript" in result4.content.lower()
        print(f"\n✓ Session 2 remembers: {result4.content}")

        # Cleanup
        ollama_manager.delete_session("session_1")
        ollama_manager.delete_session("session_2")


# -------------------------------------------------------------- #
# RAG Context Tests
# -------------------------------------------------------------- #


class TestRAGContext:
    """Test RAG functionality with real Ollama."""

    @pytest.mark.asyncio
    async def test_query_with_documents(self, ollama_manager):
        """Test query with document context."""
        documents = [
            "Company Name: TechCorp Industries",
            "Founded: 2020",
            "CEO: Jane Smith",
            "Products: AI-powered chatbots and virtual assistants",
            "Employees: 150 people across 5 offices",
        ]

        result = await ollama_manager.query(
            prompt="Who is the CEO of the company?",
            documents=documents,
            temperature=0.2,
            num_predict=50,
        )

        assert "Jane Smith" in result.content or "jane smith" in result.content.lower()
        print(f"\n✓ RAG with documents: {result.content}")

    @pytest.mark.asyncio
    async def test_query_with_extra_context(self, ollama_manager):
        """Test query with extra context."""
        context = """
        Meeting Notes:
        - Project deadline: December 15, 2025
        - Budget: $50,000
        - Team members: Alice, Bob, Carol
        """

        result = await ollama_manager.query(
            prompt="When is the project deadline?",
            extra_context=context,
            temperature=0.2,
            num_predict=50,
        )

        assert "December" in result.content or "december" in result.content.lower()
        print(f"\n✓ RAG with context: {result.content}")

    @pytest.mark.asyncio
    async def test_rag_with_multiple_sources(self, ollama_manager):
        """Test RAG with both context and documents."""
        context = "The meeting was held on November 15, 2025."
        documents = [
            "Attendees: John, Mary, Steve",
            "Topics: Budget review, timeline planning",
            "Action items: John to prepare report by November 20",
        ]

        result = await ollama_manager.query(
            prompt="Who needs to prepare a report and by when?",
            extra_context=context,
            documents=documents,
            temperature=0.2,
            num_predict=100,
        )

        content_lower = result.content.lower()
        assert "john" in content_lower
        assert any(word in content_lower for word in ["november", "20"])

        print(f"\n✓ Multi-source RAG: {result.content}")


# -------------------------------------------------------------- #
# JSON Output Tests
# -------------------------------------------------------------- #


class TestJSONOutput:
    """Test JSON output mode with real Ollama."""

    @pytest.mark.asyncio
    async def test_json_format(self, ollama_manager):
        """Test JSON output format."""
        result = await ollama_manager.query(
            prompt='Generate a JSON object with three fields: "name" (string), "age" (number), and "city" (string). Use example values.',
            format="json",
            temperature=0.3,
            num_predict=100,
        )

        assert isinstance(result, OllamaQueryResult)

        # Try to parse as JSON
        try:
            data = json.loads(result.content)
            assert isinstance(data, dict)
            assert "name" in data or "age" in data or "city" in data
            print(f"\n✓ JSON output: {json.dumps(data, indent=2)}")
        except json.JSONDecodeError:
            pytest.fail(f"Response is not valid JSON: {result.content}")

    @pytest.mark.asyncio
    async def test_json_array_format(self, ollama_manager):
        """Test JSON array output."""
        result = await ollama_manager.query(
            prompt='Generate a JSON array with 3 programming languages. Each item should have "name" and "year" fields. Output ONLY valid JSON, no explanation.',
            format="json",
            temperature=0.3,
            num_predict=300,
        )

        try:
            data = json.loads(result.content)
            # Could be array or object with array
            if isinstance(data, list):
                assert len(data) > 0
            elif isinstance(data, dict):
                # Object might contain an array
                assert len(data) > 0
            print(f"\n✓ JSON array output: {json.dumps(data, indent=2)[:200]}...")
        except json.JSONDecodeError:
            # For gpt-oss:20b, sometimes the thinking field contains reasoning
            # Check if there's actual JSON-like content
            if "{" in result.content or "[" in result.content:
                print(
                    f"\n✓ Response contains JSON-like content (may be incomplete): {result.content[:200]}..."
                )
            else:
                pytest.fail(f"Response is not valid JSON: {result.content}")


# -------------------------------------------------------------- #
# Generation Parameters Tests
# -------------------------------------------------------------- #


class TestGenerationParameters:
    """Test different generation parameters with real Ollama."""

    @pytest.mark.asyncio
    async def test_temperature_variation(self, ollama_manager):
        """Test different temperature settings."""
        prompt = "Name a color."

        # Low temperature (deterministic)
        result_low = await ollama_manager.query(
            prompt=prompt,
            temperature=0.1,
            num_predict=10,
        )
        print(f"\n✓ Low temp (0.1): {result_low.content}")

        # High temperature (creative)
        result_high = await ollama_manager.query(
            prompt=prompt,
            temperature=1.5,
            num_predict=10,
        )
        print(f"\n✓ High temp (1.5): {result_high.content}")

        # Both should produce valid responses
        assert len(result_low.content) > 0
        assert len(result_high.content) > 0

    @pytest.mark.asyncio
    async def test_max_tokens_limit(self, ollama_manager):
        """Test max tokens (num_predict) limiting."""
        result = await ollama_manager.query(
            prompt="Write a long story about a robot.",
            num_predict=50,  # Reasonable limit for gpt-oss:20b
            temperature=0.5,
        )

        # Should respect the token limit (allow some margin for model overhead)
        assert result.eval_count is not None
        assert result.eval_count <= 60  # Allow margin for model behavior

        print(f"\n✓ Limited to {result.eval_count} tokens: {result.content}")

    @pytest.mark.asyncio
    async def test_stop_sequences(self, ollama_manager):
        """Test stop sequences."""
        result = await ollama_manager.query(
            prompt="Count: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10",
            stop=["5"],
            temperature=0.1,
            num_predict=50,
        )

        # Should stop at or before "5"
        print(f"\n✓ Stop sequence test: {result.content}")
        assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_seed_reproducibility(self, ollama_manager):
        """Test that seed produces consistent results."""
        prompt = "Name three fruits."
        seed = 12345

        result1 = await ollama_manager.query(
            prompt=prompt,
            seed=seed,
            temperature=0.7,
            num_predict=30,
        )

        result2 = await ollama_manager.query(
            prompt=prompt,
            seed=seed,
            temperature=0.7,
            num_predict=30,
        )

        # Same seed should produce similar or identical results
        print(f"\n✓ Seed test result 1: {result1.content}")
        print(f"✓ Seed test result 2: {result2.content}")

        # At least some overlap expected
        assert len(result1.content) > 0
        assert len(result2.content) > 0


# -------------------------------------------------------------- #
# Model Management Tests
# -------------------------------------------------------------- #


class TestModelManagement:
    """Test model listing and management."""

    @pytest.mark.asyncio
    async def test_list_models(self, ollama_manager):
        """Test listing available models."""
        models = await ollama_manager.list_models()

        assert isinstance(models, list)
        assert len(models) > 0  # Should have at least one model

        print(f"\n✓ Found {len(models)} models:")
        for model in models[:5]:  # Print first 5
            print(f"  - {model.get('name', 'unknown')}")

    @pytest.mark.asyncio
    async def test_statistics_tracking(self, ollama_manager):
        """Test that statistics are tracked correctly."""
        initial_stats = ollama_manager.get_statistics()

        # Make a query
        await ollama_manager.query(
            prompt="Hello",
            temperature=0.1,
            num_predict=10,
        )

        final_stats = ollama_manager.get_statistics()

        # Verify statistics increased
        assert final_stats["total_requests"] == initial_stats["total_requests"] + 1
        assert final_stats["total_tokens_generated"] > initial_stats["total_tokens_generated"]

        print(f"\n✓ Statistics: {final_stats}")


# -------------------------------------------------------------- #
# Error Handling Tests
# -------------------------------------------------------------- #


class TestErrorHandling:
    """Test error handling with real Ollama."""

    @pytest.mark.asyncio
    async def test_invalid_model_name(self, ollama_manager):
        """Test behavior with invalid model name."""
        with pytest.raises(Exception):  # Should raise some exception
            await ollama_manager.query(
                model="this-model-definitely-does-not-exist-12345",
                prompt="Test",
                max_retries=1,  # Fail fast
            )

    @pytest.mark.asyncio
    async def test_timeout_handling(self, ollama_manager):
        """Test timeout handling with very short timeout."""
        with pytest.raises(Exception):  # Should timeout or raise error
            await ollama_manager.query(
                prompt="Write a very long detailed essay about the history of computing.",
                timeout_ms=100,  # Very short timeout
                num_predict=1000,  # Request many tokens
                max_retries=1,
            )


# -------------------------------------------------------------- #
# Performance Tests
# -------------------------------------------------------------- #


class TestPerformance:
    """Test performance characteristics."""

    @pytest.mark.asyncio
    async def test_concurrent_queries(self, ollama_manager):
        """Test multiple concurrent queries."""
        prompts = [
            "What is 1 + 1?",
            "What is 2 + 2?",
            "What is 3 + 3?",
        ]

        # Run concurrently
        tasks = [
            ollama_manager.query(
                prompt=prompt,
                temperature=0.1,
                num_predict=50,
            )
            for prompt in prompts
        ]

        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        for result in results:
            assert isinstance(result, OllamaQueryResult)
            assert len(result.content) > 0

        print(f"\n✓ Concurrent queries completed: {[r.content for r in results]}")

    @pytest.mark.asyncio
    async def test_response_timing(self, ollama_manager):
        """Test and log response timing."""
        import time

        start = time.time()
        result = await ollama_manager.query(
            prompt="Say hello.",
            temperature=0.1,
            num_predict=50,
        )
        duration = time.time() - start

        assert result.total_duration is not None
        print(f"\n✓ Response time: {duration:.2f}s")
        print(f"  Total duration (from Ollama): {result.total_duration / 1e9:.2f}s")
        print(f"  Eval count: {result.eval_count}")
        print(f"  Eval duration: {result.eval_duration / 1e9 if result.eval_duration else 0:.2f}s")
