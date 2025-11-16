"""Whisper server client implementation."""

import json
import logging
import os

import aiohttp

from source.server.services import WhisperServerHandler

logger = logging.getLogger(__name__)


class WhisperServerClient(WhisperServerHandler):
    """Client for Whisper.cpp server."""

    def __init__(self, name: str = "whisper_server", endpoint: str = "http://localhost:50021"):
        """
        Initialize Whisper server client.

        Args:
            name: Name of the client
            endpoint: Whisper server endpoint URL
        """
        super().__init__(name, endpoint)
        self.session: aiohttp.ClientSession | None = None

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
        """Establish connection to Whisper server."""
        try:
            self.session = aiohttp.ClientSession()
            # Test connection with a simple health check
            await self.health_check()
            self._connected = True
            logger.info(f"Connected to Whisper server at {self.endpoint}")
        except Exception as e:
            logger.error(f"Failed to connect to Whisper server: {e}")
            if self.session:
                await self.session.close()
            raise

    async def disconnect(self) -> None:
        """Close connection to Whisper server."""
        if self.session:
            await self.session.close()
            self.session = None
        self._connected = False
        logger.info("Disconnected from Whisper server")

    async def health_check(self) -> bool:
        """Check if Whisper server is healthy."""
        try:
            if not self.session:
                return False

            async with self.session.get(f"{self.endpoint}/health") as response:
                return response.status == 200
        except Exception as e:
            logger.error(f"Whisper server health check failed: {e}")
            return False

    # -------------------------------------------------------------- #
    # Handler Methods
    # -------------------------------------------------------------- #

    async def select_load_model(self, model_path: str) -> None:
        """
        Load a Whisper model on the server.

        Args:
            model_path: Path to the model file
        """
        if not self.session:
            raise RuntimeError("Not connected to Whisper server")

        try:
            data = aiohttp.FormData()
            data.add_field("model", model_path)

            async with self.session.post(f"{self.endpoint}/load", data=data) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise RuntimeError(f"Failed to load model: {error_text}")

                logger.info(f"Successfully loaded model: {model_path}")
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            raise

    async def inference(
        self,
        audio_path: str,
        word_timestamps=True,
        response_format="verbose_json",
        temperature="0.0",
        temperature_inc="0.2",
        language="en",
    ) -> str | dict:
        """
        Perform transcription on the given audio file.

        Args:
            audio_path: Path to the audio file
            word_timestamps: Whether to include word-level timestamps
            response_format: Format of the response (e.g., "verbose_json", "json", "text")
            temperature: Sampling temperature for the model
            temperature_inc: Temperature increment for fallback
            language: Language code (e.g., "en" for English)

        Returns:
            For "text" format: string with transcribed text
            For "json" or "verbose_json" format: dict with full response including timestamps
        """
        if not self.session:
            raise RuntimeError("Not connected to Whisper server")

        # Default to JSON so we can safely parse it
        response_format = response_format or "json"

        data = aiohttp.FormData()
        f = open(audio_path, "rb")  # Keep open until request is done
        try:
            data.add_field("file", f, filename=os.path.basename(audio_path))

            # Add optional parameters
            for key, value in {
                "word_timestamps": word_timestamps,
                "response_format": response_format,
                "temperature": temperature,
                "temperature_inc": temperature_inc,
                "language": language,
            }.items():
                data.add_field(key, str(value))

            async with self.session.post(f"{self.endpoint}/inference", data=data) as response:
                body = await response.text()

                if response.status != 200:
                    raise RuntimeError(f"Inference failed ({response.status}): {body}")

                # Text-only response - return as plain string
                if response_format == "text":
                    return body

                # JSON / verbose_json - return full parsed response
                result = json.loads(body)
                return result
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            raise
        finally:
            f.close()


def construct_whisper_server_client(
    endpoint: str = "http://localhost:50021",
) -> WhisperServerClient:
    """
    Construct and return a Whisper server client.

    Args:
        endpoint: Whisper server endpoint URL

    Returns:
        Configured WhisperServerClient instance
    """
    return WhisperServerClient(name="whisper_server", endpoint=endpoint)
