"""
Whisper server process wrapper.
Manages starting, stopping, and health checking the whisper-server process.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from config import config

logger = logging.getLogger(__name__)


class WhisperServer:
    """Manages the whisper-server subprocess."""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self._is_running = False

    def start_server(self) -> None:
        """
        Start the whisper-server process.

        Raises:
            RuntimeError: If server is already running or fails to start
            FileNotFoundError: If whisper binary doesn't exist
        """
        if self._is_running:
            logger.warning("Whisper server is already running")
            return

        if not config.whisper_binary_path.exists():
            raise FileNotFoundError(f"Whisper binary not found at: {config.whisper_binary_path}")

        # Build command
        cmd = [
            str(config.whisper_binary_path),
            "-p",
            "2",  # Number of processors
            "--host",
            config.whisper_host,
            "--port",
            str(config.whisper_port),
            "--model",
            str(config.whisper_model_path),
            "--public",
            str(config.whisper_public_path),
        ]

        logger.info(f"Starting whisper-server: {' '.join(cmd)}")

        try:
            # Start the process - don't capture output, let it go to parent's stdout/stderr
            self.process = subprocess.Popen(
                cmd,
                stdout=None,
                stderr=None,
            )

            # Wait for server to be ready
            self._wait_for_ready()
            self._is_running = True

            logger.info(f"Whisper server started successfully at {config.whisper_url}")

        except Exception as e:
            if self.process:
                self.process.terminate()
                self.process.wait(timeout=5)
            raise RuntimeError(f"Failed to start whisper server: {e}")

    def stop_server(self) -> None:
        """Stop the whisper-server process gracefully."""
        if not self.process:
            logger.warning("No whisper server process to stop")
            return

        logger.info("Stopping whisper server...")

        try:
            # Try graceful shutdown first
            self.process.terminate()

            # Wait up to 10 seconds for graceful shutdown
            try:
                self.process.wait(timeout=10)
                logger.info("Whisper server stopped gracefully")
            except subprocess.TimeoutExpired:
                # Force kill if still running
                logger.warning("Whisper server didn't stop gracefully, forcing kill")
                self.process.kill()
                self.process.wait(timeout=5)
                logger.info("Whisper server killed")

        except Exception as e:
            logger.error(f"Error stopping whisper server: {e}")

        finally:
            self.process = None
            self._is_running = False

    def _wait_for_ready(self, timeout: Optional[int] = None) -> None:
        """
        Wait for the whisper server to be ready by checking health endpoint.

        Args:
            timeout: Maximum seconds to wait (defaults to config.server_start_timeout)

        Raises:
            TimeoutError: If server doesn't become ready in time
        """
        if timeout is None:
            timeout = config.server_start_timeout

        health_url = f"{config.whisper_url}/"
        start_time = time.time()
        last_error = None

        logger.info(f"Waiting for whisper server to be ready (timeout: {timeout}s)...")

        while time.time() - start_time < timeout:
            try:
                response = requests.get(health_url, timeout=2)
                if response.status_code == 200:
                    logger.info("Whisper server is ready")
                    return
            except requests.exceptions.RequestException as e:
                last_error = e

            # Check if process died
            if self.process and self.process.poll() is not None:
                raise RuntimeError(
                    f"Whisper server process died with exit code {self.process.returncode}"
                )

            time.sleep(0.5)

        raise TimeoutError(
            f"Whisper server did not become ready within {timeout}s. " f"Last error: {last_error}"
        )

    def is_healthy(self) -> bool:
        """Check if the whisper server is healthy."""
        if not self._is_running or not self.process:
            return False

        # Check if process is still alive
        if self.process.poll() is not None:
            self._is_running = False
            return False

        # Check HTTP health
        try:
            response = requests.get(f"{config.whisper_url}/", timeout=2)
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False

    @property
    def is_running(self) -> bool:
        """Check if server is marked as running."""
        return self._is_running
