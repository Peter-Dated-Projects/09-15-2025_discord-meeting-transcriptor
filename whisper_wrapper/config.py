"""
Configuration loader for Whisper Flask microservice.
Loads environment variables from .env.local with sensible defaults.
"""

import os
import platform
from pathlib import Path
from typing import Optional


def get_project_root() -> Path:
    """Get the project root directory (parent of whisper_wrapper)."""
    return Path(__file__).parent.parent


def load_env_file(env_file: Optional[Path] = None) -> None:
    """Load environment variables from .env.local file."""
    if env_file is None:
        env_file = get_project_root() / ".env.local"

    if not env_file.exists():
        print(f"Warning: {env_file} not found, using defaults")
        return

    print(f"Loading environment from: {env_file}")

    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                if "=" in line:
                    key, value = line.split("=", 1)
                    # Only set if not already in environment
                    if key.strip() not in os.environ:
                        os.environ[key.strip()] = value.strip()


class Config:
    """Configuration class with sensible defaults."""

    def __init__(self):
        # Load env file first
        load_env_file()

        # Project root
        self.project_root = get_project_root()

        # Whisper server configuration
        self.whisper_host = os.getenv("WHISPER_HOST", "localhost")
        self.whisper_port = int(os.getenv("WHISPER_PORT", "50021"))
        self.whisper_url = f"http://{self.whisper_host}:{self.whisper_port}"

        # Model path
        model_path = os.getenv("WHISPER_MODEL_PATH", "assets/models/ggml-large-v2.bin")
        self.whisper_model_path = self._resolve_path(model_path)

        # Public path
        public_path = os.getenv("WHISPER_PUBLIC_PATH", "assets/whisper-public")
        self.whisper_public_path = self._resolve_path(public_path)

        # Binary paths (OS-specific)
        self.whisper_binary_path = self._get_whisper_binary_path()

        # Flask configuration
        self.flask_host = os.getenv("FLASK_HOST", "0.0.0.0")
        self.flask_port = int(os.getenv("FLASK_PORT", "5000"))
        self.flask_debug = os.getenv("FLASK_DEBUG", "False").lower() == "true"

        # Server timeouts
        self.server_start_timeout = int(os.getenv("SERVER_START_TIMEOUT", "30"))
        self.inference_timeout = int(os.getenv("INFERENCE_TIMEOUT", "300"))

    def _resolve_path(self, path: str) -> Path:
        """Resolve relative path to absolute path from project root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.project_root / path).resolve()

    def _get_whisper_binary_path(self) -> Path:
        """Get OS-specific whisper binary path."""
        system = platform.system().lower()

        if system == "darwin":  # macOS
            path = os.getenv("MAC_WHISPER_SERVER_PATH", "assets/binaries/whisper/whisper-server")
        elif system == "windows":
            path = os.getenv(
                "WINDOWS_WHISPER_SERVER_PATH", "assets/binaries/whisper/whisper-server.exe"
            )
        else:  # Linux and others
            path = os.getenv(
                "MAC_WHISPER_SERVER_PATH",  # Use same as macOS
                "assets/binaries/whisper/whisper-server",
            )

        return self._resolve_path(path)

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.whisper_binary_path.exists():
            errors.append(f"Whisper binary not found at: {self.whisper_binary_path}")

        if not self.whisper_model_path.exists():
            errors.append(f"Whisper model not found at: {self.whisper_model_path}")

        return errors


# Global config instance
config = Config()
