import subprocess

from source.server.server import ServerManager

from source.services.manager import BaseFFmpegServiceManager

# -------------------------------------------------------------- #
# FFmpeg Manager Service
# -------------------------------------------------------------- #


class FFmpegHandler:
    def __init__(self, ffmpeg_path: str):
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
            return result.returncode == 0
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
            options: Dictionary of FFmpeg options (e.g., {'-f': 's16le', '-ar': '48000'})

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

            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def create_ffmpeg_stream_process(self) -> "FFmpegConversionStream":
        return FFmpegConversionStream(self)


class FFmpegConversionStream:
    def __init__(self, ffmpeg_handler: FFmpegHandler):
        self.ffmpeg_handler = ffmpeg_handler
        self.subprocess = None
        self._is_running = False
        self._bytes_processed = 0

    # -------------------------------------------------------------- #
    # Streaming Methods
    # -------------------------------------------------------------- #

    def start_stream(self, input_path: str, output_path: str, options: dict) -> bool:
        """
        Start a streaming FFmpeg process.

        Args:
            input_path: Path to the input file or stream
            output_path: Path to the output file or stream (can be - for stdout)
            options: Dictionary of FFmpeg options

        Returns:
            True if stream started successfully, False otherwise
        """
        try:
            # Build FFmpeg command for streaming
            cmd = [self.ffmpeg_handler.ffmpeg_path, "-i", input_path]

            # Add options from the dictionary
            for key, value in options.items():
                cmd.append(key)
                if value is not None:
                    cmd.append(str(value))

            # Add output path
            cmd.append(output_path)

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

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("FFmpegManagerService initialized")
        return True

    async def on_close(self):
        return True

    # -------------------------------------------------------------- #
    # FFmpeg Management Methods
    # -------------------------------------------------------------- #
