import asyncio
import contextlib
import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles

if TYPE_CHECKING:
    from source.context import Context

from source.services.manager import Manager

# -------------------------------------------------------------- #
# Async Logging Service
# -------------------------------------------------------------- #


class AsyncLoggingService(Manager):
    """Async logging service with file locking to prevent concurrent writes."""

    def __init__(
        self,
        context: "Context",
        log_dir: str = "logs",
        log_file: str | None = None,
        use_timestamp: bool = True,
        console_output: bool = True,
    ):
        """Initialize the async logging service.

        Args:
            context: Context instance containing server and services
            log_dir: Directory to store log files
            log_file: Name of the log file (if None and use_timestamp is True,
                     a timestamped filename will be generated)
            use_timestamp: If True and log_file is None, create a timestamped log file.
                          If False, uses "app.log" as default.
            console_output: If True, all log messages are also printed to console (stdout).
        """
        super().__init__(context)
        self.log_dir = Path(log_dir)
        self.console_output = console_output

        # Generate log file name
        if log_file is None:
            if use_timestamp:
                # Create timestamped log file: app_2025-11-03_14-30-45.log
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                self.log_file = f"app_{timestamp}.log"
            else:
                self.log_file = "app.log"
        else:
            self.log_file = log_file

        self.log_path = self.log_dir / self.log_file

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

        # Log the initialization with the log file name
        await self.info(f"AsyncLoggingService initialized. Logging to: {self.log_path}")

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
        # Always print to console (stdout) with immediate flush for all log messages
        if self.console_output:
            print(message, file=sys.stdout, flush=True)

        async with self._write_lock:
            try:
                async with aiofiles.open(self.log_path, mode="a") as f:
                    await f.write(message + "\n")
            except Exception as e:
                # Print to stderr if file write fails
                error_msg = f"[ERROR] Failed to write to log file: {e}"
                print(error_msg, file=sys.stderr, flush=True)

    async def _flush_queue(self) -> None:
        """Flush all remaining messages from the queue."""
        while not self._log_queue.empty():
            try:
                message = self._log_queue.get_nowait()
                await self._write_to_file(message)
            except asyncio.QueueEmpty:
                break
