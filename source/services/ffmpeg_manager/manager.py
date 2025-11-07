import asyncio
import subprocess
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context

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
    is_pcm_to_mp3: bool = False  # Flag to use specialized PCM conversion
    bitrate: str = "128k"  # Only used for PCM to MP3 jobs
    job_id: str | None = None  # Job ID for tracking in jobs_status table
    meeting_id: str | None = None  # Meeting ID for tracking in jobs_status table


class FFmpegHandler:
    def __init__(self, ffmpeg_service_manager: BaseFFmpegServiceManager, ffmpeg_path: str):
        self.ffmpeg_service_manager = ffmpeg_service_manager
        self.ffmpeg_path = ffmpeg_path

    # -------------------------------------------------------------- #
    # FFmpeg Management Methods
    # -------------------------------------------------------------- #

    async def validate_ffmpeg(self) -> bool:
        """Validate that FFmpeg is installed and accessible."""
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        [self.ffmpeg_path, "-version"],
                        capture_output=True,
                        timeout=5,
                        text=True,
                    ),
                ),
                timeout=6.0,  # Slightly longer than subprocess timeout
            )
            is_valid = result.returncode == 0
            return is_valid
        except (FileNotFoundError, subprocess.TimeoutExpired, asyncio.TimeoutError, Exception):
            return False

    # -------------------------------------------------------------- #
    # Media Conversion Methods
    # -------------------------------------------------------------- #

    async def convert_file(
        self, input_path: str, output_path: str, options: dict
    ) -> tuple[bool, str, str]:
        """
        Convert a media file using FFmpeg with the provided options.

        Args:
            input_path: Path to the input file
            output_path: Path to the output file
            options: Dictionary of FFmpeg options (e.g., {'-f': 's16le', '-ar': '48000', 'y': None})

        Returns:
            Tuple of (success: bool, stdout: str, stderr: str)
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

            # Run FFmpeg process in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        cmd,
                        capture_output=True,
                        timeout=300,  # 5 minute timeout
                        text=True,
                    ),
                ),
                timeout=310.0,  # Slightly longer than subprocess timeout
            )

            success = result.returncode == 0
            return success, result.stdout, result.stderr
        except (subprocess.TimeoutExpired, asyncio.TimeoutError):
            return False, "", "FFmpeg process timed out"
        except Exception as e:
            return False, "", str(e)

    async def convert_pcm_to_mp3(
        self, input_path: str, output_path: str, bitrate: str = "128k"
    ) -> tuple[bool, str, str]:
        """
        Convert a raw PCM file to MP3.

        Args:
            input_path: Path to the input PCM file
            output_path: Path to the output MP3 file
            bitrate: MP3 bitrate (default: 128k)

        Returns:
            Tuple of (success: bool, stdout: str, stderr: str)
        """
        try:
            # Build FFmpeg command for PCM to MP3
            # Format options MUST come BEFORE -i for raw input
            cmd = [
                self.ffmpeg_path,
                "-f",
                "s16le",  # Input format: signed 16-bit little-endian PCM
                "-ar",
                "48000",  # Input sample rate: 48kHz (Discord's native rate)
                "-ac",
                "2",  # Input channels: stereo
                "-i",
                input_path,  # Input file
                "-codec:a",
                "libmp3lame",  # MP3 encoder
                "-b:a",
                bitrate,  # Output bitrate
                "-y",  # Overwrite output file
                output_path,
            ]

            # Run FFmpeg process in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        cmd,
                        capture_output=True,
                        timeout=300,  # 5 minute timeout
                        text=True,
                    ),
                ),
                timeout=310.0,  # Slightly longer than subprocess timeout
            )

            success = result.returncode == 0
            return success, result.stdout, result.stderr
        except (subprocess.TimeoutExpired, asyncio.TimeoutError):
            return False, "", "FFmpeg process timed out"
        except Exception as e:
            return False, "", str(e)

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
        self.ffmpeg_handler.ffmpeg_service_manager.services.file_service_manager._acquire_file_lock_oneshot(
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

    async def close_stream(self) -> None:
        """Close the streaming FFmpeg process gracefully."""
        if self.subprocess and self._is_running:
            try:
                # Send QUIT command to FFmpeg
                if self.subprocess.stdin:
                    self.subprocess.stdin.write(b"q")
                    self.subprocess.stdin.flush()

                # Wait for process to terminate (with timeout) - NON-BLOCKING
                try:
                    loop = asyncio.get_event_loop()
                    stdout_data, stderr_data = await asyncio.wait_for(
                        loop.run_in_executor(None, self.subprocess.communicate), timeout=5.0
                    )

                    # Log captured stdout and stderr when process exits
                    if stdout_data:
                        await self.ffmpeg_handler.ffmpeg_service_manager.services.logging_service.info(
                            f"FFmpeg STDOUT:\n{stdout_data.decode('utf-8', errors='replace')}"
                        )
                    if stderr_data:
                        await self.ffmpeg_handler.ffmpeg_service_manager.services.logging_service.info(
                            f"FFmpeg STDERR:\n{stderr_data.decode('utf-8', errors='replace')}"
                        )
                except asyncio.TimeoutError:
                    # Force kill if timeout expires
                    if self.subprocess.poll() is None:
                        self.subprocess.kill()
                        loop = asyncio.get_event_loop()
                        stdout_data, stderr_data = await loop.run_in_executor(
                            None, self.subprocess.communicate
                        )

                        # Log captured stdout and stderr from killed process
                        if stdout_data:
                            await self.ffmpeg_handler.ffmpeg_service_manager.services.logging_service.info(
                                f"FFmpeg STDOUT (killed):\n{stdout_data.decode('utf-8', errors='replace')}"
                            )
                        if stderr_data:
                            await self.ffmpeg_handler.ffmpeg_service_manager.services.logging_service.error(
                                f"FFmpeg STDERR (killed):\n{stderr_data.decode('utf-8', errors='replace')}"
                            )

            except BrokenPipeError:
                # Force kill if pipe breaks
                if self.subprocess.poll() is None:
                    self.subprocess.kill()
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.subprocess.wait)
            finally:
                self._is_running = False
                self.subprocess = None

                # Release file lock
                self.ffmpeg_handler.ffmpeg_service_manager.services.file_service_manager._release_file_lock_oneshot(
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

    def __init__(self, context: "Context", ffmpeg_path: str):
        super().__init__(context)

        self.ffmpeg_path = ffmpeg_path
        self.handler = FFmpegHandler(self, ffmpeg_path)

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
        if await self.handler.validate_ffmpeg():
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
            with suppress(asyncio.CancelledError):
                await self._worker_task
            await self.services.logging_service.info("FFmpeg worker task stopped")
        return True

    async def _worker(self):
        """Background worker that processes FFmpeg jobs from the queue."""
        while True:
            try:
                job = await self._jobs.get()
                await self.services.logging_service.info(
                    f"Processing FFmpeg conversion: {job.input_path} -> {job.output_path}"
                )

                # Log job start in jobs_status table if job tracking is enabled
                if job.job_id and job.meeting_id and self.services.sql_logging_service_manager:

                    from source.server.sql_models import JobsStatus, JobsType
                    from source.utils import get_current_timestamp_est

                    try:
                        await self.services.sql_logging_service_manager.log_job_status_event(
                            job_type=JobsType.TEMP_TRANSCODING,
                            job_id=job.job_id,
                            meeting_id=job.meeting_id,
                            created_at=get_current_timestamp_est(),
                            status=JobsStatus.IN_PROGRESS,
                            started_at=get_current_timestamp_est(),
                        )
                    except Exception as e:
                        await self.services.logging_service.error(
                            f"Failed to log temp transcoding job start status: {str(e)}"
                        )

                try:
                    # Choose conversion method based on job type
                    if job.is_pcm_to_mp3:
                        ok, stdout, stderr = await self.handler.convert_pcm_to_mp3(
                            job.input_path,
                            job.output_path,
                            job.bitrate,
                        )
                    else:
                        ok, stdout, stderr = await self.handler.convert_file(
                            job.input_path,
                            job.output_path,
                            job.options,
                        )

                    job.fut.set_result(bool(ok))

                    # Log FFmpeg output
                    if stdout:
                        await self.services.logging_service.debug(f"FFmpeg STDOUT:\n{stdout}")
                    if stderr:
                        await self.services.logging_service.debug(f"FFmpeg STDERR:\n{stderr}")

                    if ok:
                        await self.services.logging_service.info(
                            f"FFmpeg conversion completed: {job.input_path} -> {job.output_path}"
                        )
                    else:
                        await self.services.logging_service.error(
                            f"FFmpeg conversion failed for {job.input_path} to {job.output_path}"
                        )

                    # Log job completion in jobs_status table if job tracking is enabled
                    if job.job_id and job.meeting_id and self.services.sql_logging_service_manager:

                        from source.server.sql_models import JobsStatus, JobsType
                        from source.utils import get_current_timestamp_est

                        try:
                            await self.services.sql_logging_service_manager.log_job_status_event(
                                job_type=JobsType.TEMP_TRANSCODING,
                                job_id=job.job_id,
                                meeting_id=job.meeting_id,
                                created_at=get_current_timestamp_est(),
                                status=JobsStatus.COMPLETED if ok else JobsStatus.FAILED,
                                finished_at=get_current_timestamp_est(),
                            )
                        except Exception as e:
                            await self.services.logging_service.error(
                                f"Failed to log temp transcoding job completion status: {str(e)}"
                            )

                except Exception as e:
                    job.fut.set_exception(e)
                    await self.services.logging_service.error(
                        f"FFmpeg conversion exception for {job.input_path}: {str(e)}"
                    )

                    # Log job failure in jobs_status table if job tracking is enabled
                    if job.job_id and job.meeting_id and self.services.sql_logging_service_manager:
                        from source.server.sql_models import JobsStatus, JobsType
                        from source.utils import get_current_timestamp_est

                        try:
                            await self.services.sql_logging_service_manager.log_job_status_event(
                                job_type=JobsType.TEMP_TRANSCODING,
                                job_id=job.job_id,
                                meeting_id=job.meeting_id,
                                created_at=get_current_timestamp_est(),
                                status=JobsStatus.FAILED,
                                finished_at=get_current_timestamp_est(),
                            )
                        except Exception as log_error:
                            await self.services.logging_service.error(
                                f"Failed to log temp transcoding job failure status: {str(log_error)}"
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

    async def queue_pcm_to_mp3(
        self,
        input_path: str,
        output_path: str,
        bitrate: str = "128k",
        callback: callable = None,
        job_id: str | None = None,
        meeting_id: str | None = None,
    ) -> bool:
        """
        Queue a PCM to MP3 conversion job with optional callback and job tracking.

        Args:
            input_path: Path to the input PCM file
            output_path: Path to the output MP3 file
            bitrate: MP3 bitrate (default: 128k)
            callback: Optional async callback function called with success status on completion
            job_id: Optional 16-character job ID for tracking in jobs_status table
            meeting_id: Optional 16-character meeting ID for tracking in jobs_status table

        Returns:
            True if job was queued successfully, False otherwise
        """
        await self.services.logging_service.info(
            f"Queuing PCM to MP3 conversion: {input_path} -> {output_path}"
        )

        if self._jobs is None:
            self._jobs = asyncio.Queue(maxsize=10)
            await self.services.logging_service.info("Initialized FFmpeg job queue")

        # Start the worker task if not already running
        if not self._worker_task or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            await self.services.logging_service.info("Started FFmpeg worker task")

        if self._jobs.full():
            await self.services.logging_service.warning("FFmpeg job queue full")
            if callback:
                await callback(False)
            return False

        # Ensure parent directory exists
        await self.services.file_service_manager.ensure_parent_dir(output_path)

        # Log initial PENDING status if job tracking is enabled
        if job_id and meeting_id and self.services.sql_logging_service_manager:
            from source.server.sql_models import JobsStatus, JobsType
            from source.utils import get_current_timestamp_est

            try:
                await self.services.sql_logging_service_manager.log_job_status_event(
                    job_type=JobsType.TEMP_TRANSCODING,
                    job_id=job_id,
                    meeting_id=meeting_id,
                    created_at=get_current_timestamp_est(),
                    status=JobsStatus.PENDING,
                )
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to log temp transcoding job pending status: {str(e)}"
                )

        # Create a Future for this specific job
        fut = asyncio.get_running_loop().create_future()

        # Add callback to the future if provided
        if callback:

            def done_callback(f):
                try:
                    success = f.result()
                    asyncio.create_task(callback(success))
                except Exception:
                    asyncio.create_task(callback(False))

            fut.add_done_callback(done_callback)

        # Create job with PCM flag set
        job = FFJob(
            input_path=input_path,
            output_path=output_path,
            options={},  # Not used for PCM conversion
            fut=fut,
            is_pcm_to_mp3=True,
            bitrate=bitrate,
            job_id=job_id,
            meeting_id=meeting_id,
        )

        # Enqueue the job
        await self._jobs.put(job)
        await self.services.logging_service.info(
            f"Queued PCM to MP3 job: {input_path} -> {output_path} (queue size: {self._jobs.qsize()})"
        )

        return True

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
        await self.services.logging_service.info(
            f"Starting queue_mp3_to_whisper_format_job: {input_path} -> {output_path}"
        )

        if self._jobs is None:
            self._jobs = asyncio.Queue(maxsize=10)
            await self.services.logging_service.info("Initialized FFmpeg job queue")

        # Start the worker task if not already running
        if not self._worker_task or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            await self.services.logging_service.info("Started FFmpeg worker task")

        if self._jobs.full():
            await self.services.logging_service.warning("FFmpeg job queue full")
            return False

        # Ensure parent directory exists; let ffmpeg create/overwrite output file itself
        await self.services.file_service_manager.ensure_parent_dir(output_path)
        await self.services.logging_service.debug(f"Ensured parent directory for {output_path}")

        # Create a Future for this specific job
        options = {
            "-ar": "16000",
            "-ac": "1",
            "-acodec": "pcm_s16le",
            "-y": None,
        }
        fut = asyncio.get_running_loop().create_future()
        job = FFJob(input_path, output_path, options, fut)

        # Enqueue the job
        await self._jobs.put(job)
        await self.services.logging_service.info(
            f"Queued FFmpeg job: {input_path} -> {output_path} (queue size: {self._jobs.qsize()})"
        )

        # Wait only for THIS job to complete
        try:
            await self.services.logging_service.info(
                f"Waiting for FFmpeg job to complete: {input_path} -> {output_path}"
            )
            # Optional: Add timeout (e.g., 10 minutes for large files)
            result = await asyncio.wait_for(fut, timeout=600)
            await self.services.logging_service.info(
                f"FFmpeg job completed successfully: {input_path} -> {output_path}"
            )
            return result
        except asyncio.TimeoutError:
            await self.services.logging_service.error(
                f"FFmpeg job timed out: {input_path} -> {output_path}"
            )
            return False
        except Exception as e:
            await self.services.logging_service.error(
                f"FFmpeg job failed with exception: {input_path} -> {output_path}: {str(e)}"
            )
            return False
