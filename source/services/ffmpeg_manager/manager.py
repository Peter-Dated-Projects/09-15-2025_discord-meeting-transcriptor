import asyncio
import subprocess
from dataclasses import dataclass

from source.server.server import ServerManager
from source.services.manager import BaseFFmpegServiceManager

# -------------------------------------------------------------- #
# FFmpeg Manager Service
# -------------------------------------------------------------- #


@dataclass
class FFJob:
    """Represents a single FFmpeg conversion job with its own Future for completion tracking."""

    input_path: str
    output_path: str
    options: dict
    fut: asyncio.Future  # Set to True/False on completion


class FFmpegHandler:
    def __init__(self, ffmpeg_service_manager: BaseFFmpegServiceManager, ffmpeg_path: str):
        self.ffmpeg_service_manager = ffmpeg_service_manager
        self.ffmpeg_path = ffmpeg_path

    # -------------------------------------------------------------- #
    # FFmpeg Management Methods
    # -------------------------------------------------------------- #

    def validate_ffmpeg(self) -> bool:
        """Validate that FFmpeg is installed and accessible."""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                timeout=5,
                text=True,
            )
            is_valid = result.returncode == 0
            return is_valid
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            return False

    # -------------------------------------------------------------- #
    # Media Conversion Methods
    # -------------------------------------------------------------- #

    def convert_file(self, input_path: str, output_path: str, options: dict) -> bool:
        """
        Convert a media file using FFmpeg with the provided options.

        Args:
            input_path: Path to the input file
            output_path: Path to the output file
            options: Dictionary of FFmpeg options (e.g., {'-f': 's16le', '-ar': '48000', 'y': None})

        Returns:
            True if conversion was successful, False otherwise
        """
        try:
            # Build FFmpeg command
            cmd = [self.ffmpeg_path, "-i", input_path]

            # Add options from the dictionary
            for key, value in options.items():
                cmd.append(key)
                if value is not None:
                    cmd.append(str(value))

            # Add output path
            cmd.append(output_path)

            # Run FFmpeg process
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300,  # 5 minute timeout
                text=True,
            )

            success = result.returncode == 0
            if success:
                pass  # Logging will be done by FFmpegManagerService
            return success
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def create_ffmpeg_stream_process(self) -> "FFmpegConversionStream":
        return FFmpegConversionStream(self)

    def create_pcm_to_mp3_stream_process(self, output_file: str) -> "FFmpegConversionStream":
        """Create a new FFmpeg conversion stream for PCM to MP3 conversion."""
        return FFmpegConversionStream(self, self.ffmpeg_service_manager, output_file=output_file)


class FFmpegConversionStream:
    def __init__(
        self,
        ffmpeg_handler: FFmpegHandler,
        ffmpeg_service_manager: BaseFFmpegServiceManager,
        output_file: str,
    ):
        self.ffmpeg_handler = ffmpeg_handler
        self.ffmpeg_service_manager = ffmpeg_service_manager
        self.output_file = output_file

        self.subprocess = None
        self._is_running = False
        self._bytes_processed = 0

    # -------------------------------------------------------------- #
    # Streaming Methods
    # -------------------------------------------------------------- #

    def start_stream(self, options: dict) -> bool:
        """
        Start a streaming FFmpeg process.

        Args:
            input_path: Path to the input file or stream
            output_path: Path to the output file or stream (can be - for stdout)
            options: Dictionary of FFmpeg options

        Returns:
            True if stream started successfully, False otherwise
        """

        # Use File Manager to lock output file
        self.ffmpeg_handler.ffmpeg_service_manager.services.file_service_manager._acquire_file_lock(
            self.output_file
        )

        try:
            # Build FFmpeg command for streaming from STDIN
            cmd = [self.ffmpeg_handler.ffmpeg_path, "-i", "-"]

            # Add options from the dictionary
            for key, value in options.items():
                cmd.append(key)
                if value is not None:
                    cmd.append(str(value))

            # Add output path
            cmd.append(self.output_file)

            # Start the subprocess with pipes for stdin/stdout/stderr
            self.subprocess = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,  # Unbuffered
            )
            self._is_running = True
            return True
        except Exception:
            self._is_running = False
            return False

    def close_stream(self) -> None:
        """Close the streaming FFmpeg process gracefully."""
        if self.subprocess and self._is_running:
            try:
                # Send QUIT command to FFmpeg
                if self.subprocess.stdin:
                    self.subprocess.stdin.write(b"q")
                    self.subprocess.stdin.flush()
                # Wait for process to terminate (with timeout)
                self.subprocess.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                # Force kill if graceful shutdown fails
                if self.subprocess.poll() is None:
                    self.subprocess.kill()
                    self.subprocess.wait()
            finally:
                self._is_running = False
                self.subprocess = None

                # Release file lock
                self.ffmpeg_handler.ffmpeg_service_manager.services.file_service_manager._release_file_lock(
                    self.output_file
                )

    def get_stream_status(self) -> dict:
        """
        Get the current status of the FFmpeg stream.

        Returns:
            Dictionary with status information including bytes processed
        """
        if self.subprocess is None:
            return {
                "running": False,
                "pid": None,
                "returncode": None,
                "bytes_processed": self._bytes_processed,
            }

        returncode = self.subprocess.poll()
        return {
            "running": self._is_running and returncode is None,
            "pid": self.subprocess.pid if self.subprocess else None,
            "returncode": returncode,
            "bytes_processed": self._bytes_processed,
        }

    def push_to_stream(self, data: bytes) -> None:
        """
        Push data to the FFmpeg input stream.

        Args:
            data: Bytes to write to the FFmpeg stdin
        """
        if self.subprocess and self._is_running and self.subprocess.stdin:
            try:
                self.subprocess.stdin.write(data)
                self.subprocess.stdin.flush()
                # Track processed bytes
                self._bytes_processed += len(data)
            except (BrokenPipeError, Exception):
                self._is_running = False


class FFmpegManagerService(BaseFFmpegServiceManager):
    """Service for managing FFmpeg operations."""

    def __init__(self, server: ServerManager, ffmpeg_path: str):
        super().__init__(server)

        self.ffmpeg_path = ffmpeg_path
        self.handler = FFmpegHandler(ffmpeg_path)

        self._jobs: asyncio.Queue[FFJob] | None = None
        self._worker_task: asyncio.Task | None = None

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("FFmpegManagerService initialized")

        # Initialize the job queue (needs to be done within an async context)
        if self._jobs is None:
            self._jobs = asyncio.Queue(maxsize=10)

        # Validate FFmpeg installation
        if self.handler.validate_ffmpeg():
            await self.services.logging_service.info(
                f"FFmpeg validated at path: {self.ffmpeg_path}"
            )
        else:
            await self.services.logging_service.warning(
                f"FFmpeg validation failed at path: {self.ffmpeg_path}"
            )

        # Start the background worker task
        if not self._worker_task:
            self._worker_task = asyncio.create_task(self._worker())
            await self.services.logging_service.info("FFmpeg worker task started")

        return True

    async def on_close(self):
        # Cancel the worker task if it's running
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            await self.services.logging_service.info("FFmpeg worker task stopped")
        return True

    async def _worker(self):
        """Background worker that processes FFmpeg jobs from the queue."""
        while True:
            try:
                job = await self._jobs.get()
                await self.services.logging_service.info(
                    f"Processing FFmpeg conversion: {job.input_path} → {job.output_path}"
                )
                try:
                    # Run the synchronous conversion in a thread pool to avoid blocking
                    loop = asyncio.get_running_loop()
                    ok = await loop.run_in_executor(
                        None,
                        self.handler.convert_file,
                        job.input_path,
                        job.output_path,
                        job.options,
                    )
                    job.fut.set_result(bool(ok))
                    if ok:
                        await self.services.logging_service.info(
                            f"FFmpeg conversion completed: {job.input_path} → {job.output_path}"
                        )
                    else:
                        await self.services.logging_service.error(
                            f"FFmpeg conversion failed for {job.input_path} to {job.output_path}"
                        )
                except Exception as e:
                    job.fut.set_exception(e)
                    await self.services.logging_service.error(
                        f"FFmpeg conversion exception for {job.input_path}: {str(e)}"
                    )
                finally:
                    self._jobs.task_done()
            except asyncio.CancelledError:
                # Worker task was cancelled during shutdown
                break
            except Exception as e:
                # Log unexpected errors but keep the worker running
                await self.services.logging_service.error(
                    f"Unexpected error in FFmpeg worker: {str(e)}"
                )

    # -------------------------------------------------------------- #
    # FFmpeg Management Methods
    # -------------------------------------------------------------- #

    def get_ffmpeg_path(self) -> str:
        """Get the FFmpeg executable path."""
        return self.ffmpeg_path

    async def create_pcm_to_mp3_stream_handler(self):
        return self.handler.create_pcm_to_mp3_stream_process()

    async def queue_mp3_to_whisper_format_job(self, input_path: str, output_path: str) -> bool:
        """
        Queue an MP3 to Whisper format conversion job and wait for its completion.

        Args:
            input_path: Path to the input MP3 file
            output_path: Path to the output file
            options: Dictionary of FFmpeg options

        Returns:
            True if conversion was successful, False otherwise
        """
        if self._jobs.full():
            await self.services.logging_service.warning("FFmpeg job queue full")
            return False

        # Ensure parent directory exists; let ffmpeg create/overwrite output file itself
        self.services.file_service_manager.ensure_parent_dir(output_path)

        # Create a Future for this specific job
        options = {
            "ar": "16000",
            "ac": "1",
            "-acodec": "pcm_s16le",
            "-y": None,
        }
        fut = asyncio.get_running_loop().create_future()
        job = FFJob(input_path, output_path, options, fut)

        # Enqueue the job
        await self._jobs.put(job)
        await self.services.logging_service.info(
            f"Queued FFmpeg job: {input_path} → {output_path} (queue size: {self._jobs.qsize()})"
        )

        # Wait only for THIS job to complete
        try:
            # Optional: Add timeout (e.g., 10 minutes for large files)
            return await asyncio.wait_for(fut, timeout=600)
        except asyncio.TimeoutError:
            await self.services.logging_service.error(
                f"FFmpeg job timed out: {input_path} → {output_path}"
            )
            return False
        except Exception as e:
            await self.services.logging_service.error(
                f"FFmpeg job failed with exception: {input_path} → {output_path}: {str(e)}"
            )
            return False
