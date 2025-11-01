import asyncio
import contextlib
from datetime import datetime
from pathlib import Path

import aiofiles

from source.server.server import ServerManager
from source.services.manager import Manager

# -------------------------------------------------------------- #
# Async Logging Service
# -------------------------------------------------------------- #


class AsyncLoggingService(Manager):
    """Async logging service with file locking to prevent concurrent writes."""

    def __init__(
        self,
        server: ServerManager,
        log_dir: str = "logs",
        log_file: str = "app.log",
    ):
        """Initialize the async logging service.

        Args:
            server: ServerManager instance
            log_dir: Directory to store log files
            log_file: Name of the log file
        """
        super().__init__(server)
        self.log_dir = Path(log_dir)
        self.log_file = log_file
        self.log_path = self.log_dir / log_file

        # Create lock for serializing writes
        self._write_lock = asyncio.Lock()

        # Queue for pending log messages
        self._log_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services) -> None:
        """Initialize logging service on start."""
        await super().on_start(services)

        # Create log directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Start background writer task
        self._writer_task = asyncio.create_task(self._process_log_queue())

    async def on_close(self) -> None:
        """Clean up on close."""
        await super().on_close()

        # Stop the writer task
        if self._writer_task:
            self._writer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer_task

        # Flush remaining logs
        await self._flush_queue()

    # -------------------------------------------------------------- #
    # Public Logging Methods
    # -------------------------------------------------------------- #

    async def log(self, message: str, level: str = "INFO") -> None:
        """Queue a log message.

        Args:
            message: The log message
            level: Log level (INFO, DEBUG, WARNING, ERROR, CRITICAL)
        """
        timestamp = datetime.now().isoformat()
        formatted_message = f"[{timestamp}] [{level}] {message}"

        await self._log_queue.put(formatted_message)

    async def debug(self, message: str) -> None:
        """Log a debug message."""
        await self.log(message, "DEBUG")

    async def info(self, message: str) -> None:
        """Log an info message."""
        await self.log(message, "INFO")

    async def warning(self, message: str) -> None:
        """Log a warning message."""
        await self.log(message, "WARNING")

    async def error(self, message: str) -> None:
        """Log an error message."""
        await self.log(message, "ERROR")

    async def critical(self, message: str) -> None:
        """Log a critical message."""
        await self.log(message, "CRITICAL")

    # -------------------------------------------------------------- #
    # Private Methods
    # -------------------------------------------------------------- #

    async def _process_log_queue(self) -> None:
        """Process log messages from the queue continuously."""
        try:
            while True:
                message = await self._log_queue.get()
                await self._write_to_file(message)
                self._log_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _write_to_file(self, message: str) -> None:
        """Write a message to the log file with locking.

        Args:
            message: The formatted log message to write
        """
        async with self._write_lock:
            try:
                async with aiofiles.open(self.log_path, mode="a") as f:
                    await f.write(message + "\n")
            except Exception as e:
                # Print to stderr if file write fails
                print(f"Failed to write to log file: {e}", flush=True)

    async def _flush_queue(self) -> None:
        """Flush all remaining messages from the queue."""
        while not self._log_queue.empty():
            try:
                message = self._log_queue.get_nowait()
                await self._write_to_file(message)
            except asyncio.QueueEmpty:
                break
