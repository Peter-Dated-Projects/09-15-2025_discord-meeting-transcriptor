"""
Mock Whisper server client for testing.

This module provides a mock Whisper server implementation for testing
without requiring a running Whisper server.
"""

import logging
from typing import Any

from source.server.services import WhisperServerHandler

logger = logging.getLogger(__name__)


class MockWhisperServerClient(WhisperServerHandler):
    """Mock Whisper server client for testing."""

    def __init__(self, name: str = "test_whisper_server"):
        """
        Initialize mock Whisper server client.

        Args:
            name: Name of the client
        """
        super().__init__(name, "mock://localhost:50021")
        self.loaded_model: str | None = None
        self.transcriptions: dict[str, str] = {}

    # -------------------------------------------------------------- #
    # Handler Methods
    # -------------------------------------------------------------- #

    async def on_startup(self) -> None:
        """Actions to perform on server startup."""
        pass

    async def on_close(self) -> None:
        """Actions to perform on server close."""
        pass

    # -------------------------------------------------------------- #
    # Server Management
    # -------------------------------------------------------------- #

    async def connect(self) -> None:
        """Establish connection to mock Whisper server."""
        self._connected = True
        logger.info(f"[{self.name}] Connected to mock Whisper server")

    async def disconnect(self) -> None:
        """Close connection to mock Whisper server."""
        self._connected = False
        self.loaded_model = None
        self.transcriptions = {}
        logger.info(f"[{self.name}] Disconnected from mock Whisper server")

    async def health_check(self) -> bool:
        """Check if Whisper server is healthy."""
        return self._connected

    # -------------------------------------------------------------- #
    # Handler Methods
    # -------------------------------------------------------------- #

    async def select_load_model(self, model_path: str) -> None:
        """
        Load a Whisper model on the server (mock).

        Args:
            model_path: Path to the model file
        """
        if not self._connected:
            raise RuntimeError("Not connected to Whisper server")

        self.loaded_model = model_path
        logger.info(f"[{self.name}] Loaded model: {model_path}")

    async def inference(self, audio_path: str) -> str:
        """
        Perform transcription on the given audio file (mock).

        Args:
            audio_path: Path to the audio file

        Returns:
            Transcribed text (mocked)
        """
        if not self._connected:
            raise RuntimeError("Not connected to Whisper server")

        if not self.loaded_model:
            raise RuntimeError("No model loaded")

        # Return pre-configured transcription or generate a mock one
        if audio_path in self.transcriptions:
            return self.transcriptions[audio_path]

        # Generate mock transcription
        mock_transcription = f"Mock transcription for {audio_path}"
        return mock_transcription

    # -------------------------------------------------------------- #
    # Test Helper Methods
    # -------------------------------------------------------------- #

    def set_transcription(self, audio_path: str, transcription: str) -> None:
        """
        Set a mock transcription for a specific audio file.

        Args:
            audio_path: Path to the audio file
            transcription: Mock transcription text
        """
        self.transcriptions[audio_path] = transcription

    def reset(self) -> None:
        """Reset the mock server state."""
        self.loaded_model = None
        self.transcriptions = {}
