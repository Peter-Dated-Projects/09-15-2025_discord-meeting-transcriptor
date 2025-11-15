"""
Integration tests for Whisper server client.

These tests require:
1. Whisper server running (./dy.sh up)
2. Audio test files in tests/assets/
"""

import os
from pathlib import Path

import pytest

from source.server.common.whisper_server import WhisperServerClient


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def whisper_endpoint() -> str:
    """Get Whisper server endpoint from environment."""
    host = os.getenv("WHISPER_HOST", "localhost")
    port = os.getenv("WHISPER_PORT", "50021")
    return f"http://{host}:{port}"


@pytest.fixture
def audio_file_path() -> Path:
    """Get path to test audio file."""
    # Go up 4 levels: test_whisper_client.py -> whisper_server -> services -> integration -> tests
    test_dir = Path(__file__).parent.parent.parent.parent
    audio_path = test_dir / "assets" / "audio-recording-1.m4a"

    print(f"Using test audio file at: {audio_path}")

    if not audio_path.exists():
        pytest.skip(f"Test audio file not found: {audio_path}")

    return audio_path


@pytest.fixture
async def whisper_client(whisper_endpoint: str):
    """Create and connect Whisper server client."""
    client = WhisperServerClient(endpoint=whisper_endpoint)

    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


# ============================================================================
# Tests
# ============================================================================


@pytest.mark.asyncio
async def test_whisper_client_connection(whisper_endpoint: str):
    """Test that we can connect to Whisper server."""
    client = WhisperServerClient(endpoint=whisper_endpoint)

    try:
        await client.connect()
        assert client.is_connected
        assert client.session is not None
    finally:
        await client.disconnect()
        assert not client.is_connected


@pytest.mark.asyncio
async def test_whisper_health_check(whisper_client: WhisperServerClient):
    """Test Whisper server health check."""
    is_healthy = await whisper_client.health_check()
    assert is_healthy, "Whisper server health check failed"


@pytest.mark.asyncio
@pytest.mark.slow
async def test_whisper_inference_default_json(
    whisper_client: WhisperServerClient, audio_file_path: Path
):
    """Test basic inference with default JSON response format."""
    result = await whisper_client.inference(str(audio_file_path))

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\nTranscription (JSON): {result}")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_whisper_inference_text_format(
    whisper_client: WhisperServerClient, audio_file_path: Path
):
    """Test inference with text response format."""
    result = await whisper_client.inference(str(audio_file_path), response_format="text")

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\nTranscription (text): {result}")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_whisper_inference_verbose_json(
    whisper_client: WhisperServerClient, audio_file_path: Path
):
    """Test inference with verbose JSON response format."""
    result = await whisper_client.inference(str(audio_file_path), response_format="verbose_json")

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\nTranscription (verbose_json): {result}")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_whisper_inference_with_temperature(
    whisper_client: WhisperServerClient, audio_file_path: Path
):
    """Test inference with custom temperature parameter."""
    result = await whisper_client.inference(
        str(audio_file_path), temperature="0.0", temperature_inc="0.2"
    )

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
@pytest.mark.slow
async def test_whisper_inference_with_language(
    whisper_client: WhisperServerClient, audio_file_path: Path
):
    """Test inference with language parameter."""
    result = await whisper_client.inference(str(audio_file_path), language="en")

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.asyncio
async def test_whisper_inference_nonexistent_file(whisper_client: WhisperServerClient):
    """Test inference with nonexistent file raises appropriate error."""
    with pytest.raises(FileNotFoundError):
        await whisper_client.inference("/path/to/nonexistent/file.wav")


@pytest.mark.asyncio
async def test_whisper_inference_without_connection():
    """Test that inference fails when not connected."""
    client = WhisperServerClient()

    with pytest.raises(RuntimeError, match="Not connected to Whisper server"):
        await client.inference("/some/path.wav")


@pytest.mark.asyncio
async def test_whisper_client_disconnect_idempotent(whisper_endpoint: str):
    """Test that disconnecting multiple times is safe."""
    client = WhisperServerClient(endpoint=whisper_endpoint)

    await client.connect()
    await client.disconnect()
    await client.disconnect()  # Should not raise

    assert not client.is_connected


# ============================================================================
# Parametrized Tests
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.slow
@pytest.mark.parametrize("response_format", ["json", "text", "verbose_json"])
async def test_whisper_inference_all_formats(
    whisper_client: WhisperServerClient, audio_file_path: Path, response_format: str
):
    """Test inference with all supported response formats."""
    result = await whisper_client.inference(str(audio_file_path), response_format=response_format)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    print(f"\nTranscription ({response_format}): {result[:100]}...")


@pytest.mark.asyncio
@pytest.mark.slow
@pytest.mark.parametrize("temperature", ["0.0", "0.2", "0.5"])
async def test_whisper_inference_temperatures(
    whisper_client: WhisperServerClient, audio_file_path: Path, temperature: str
):
    """Test inference with different temperature values."""
    result = await whisper_client.inference(str(audio_file_path), temperature=temperature)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
