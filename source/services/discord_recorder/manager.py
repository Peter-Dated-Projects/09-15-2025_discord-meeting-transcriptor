import asyncio
import os
from collections import Counter
from contextlib import suppress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from discord import sinks

from source.server.server import ServerManager
from source.server.sql_models import TranscodeStatus
from source.services.manager import BaseDiscordRecorderServiceManager, ServicesManager
from source.utils import generate_16_char_uuid, get_current_timestamp_est

# -------------------------------------------------------------- #
# Configuration Constants
# -------------------------------------------------------------- #


class DiscordRecorderConstants:
    """Configuration constants for Discord recording."""

    # Flush cycle
    FLUSH_INTERVAL_SECONDS = 10  # Configurable: flush buffer every N seconds

    # FFmpeg encoding
    MP3_BITRATE = "128k"  # 128 kbps

    # Transcode timeout
    TRANSCODE_TIMEOUT_SECONDS = 300  # 5 minutes

    # Cleanup configuration
    CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour
    TEMP_RECORDING_TTL_HOURS = 24  # 24 hours

    # Batch deletion
    MAX_DELETE_BATCH_SIZE = 100


# -------------------------------------------------------------- #
# Discord Recorder Service Manager
# -------------------------------------------------------------- #


class DiscordSessionHandler:
    """
    Handler for managing individual Discord recording sessions.

    This class handles:
    - Multi-user audio recording via Pycord's recording API
    - Per-user audio buffering and periodic flushing
    - Temp recording creation in SQL
    - FFmpeg job queuing
    - Session lifecycle management

    Recording Architecture:
    - Uses discord.sinks.WaveSink to capture per-user audio streams
    - Periodically flushes audio for ALL users in the call
    - Each user's audio is stored as separate temp recordings
    """

    def __init__(
        self,
        discord_voice_client: discord.VoiceClient,
        channel_id: int,
        meeting_id: str,
        user_id: str,
        guild_id: str,
        services: "ServicesManager",
    ):
        self.discord_voice_client = discord_voice_client
        self.channel_id = channel_id
        self.meeting_id = meeting_id
        self.user_id = user_id  # Bot user ID (for SQL tracking)
        self.guild_id = guild_id
        self.services = services
        self.start_time = get_current_timestamp_est()
        self.is_recording = False

        # Per-user audio buffers: {user_id: bytearray}
        self._user_audio_buffers: dict[int, bytearray] = {}

        # Track chunk counters per user: {user_id: int}
        self._user_chunk_counters: dict[int, int] = {}

        # Track temp recording IDs per user: {user_id: list[str]}
        self._user_temp_recording_ids: dict[int, list[str]] = {}

        # Track how many bytes we've read from each user's sink: {user_id: int}
        self._user_bytes_read: dict[int, int] = {}

        # Pycord recording sink
        self._sink: "discord.sinks.WaveSink | None" = None

        # Shutdown flag
        self._is_shutting_down = False

        self._flush_task: asyncio.Task | None = None

    # -------------------------------------------------------------- #
    # Session Lifecycle Methods
    # -------------------------------------------------------------- #

    async def start_recording(self) -> None:
        """Start the recording session using Pycord's recording API."""
        if self.is_recording:
            await self.services.logging_service.warning(
                f"Session {self.channel_id} already recording"
            )
            return

        self.is_recording = True
        self._is_shutting_down = False

        # Initialize per-user tracking
        self._user_audio_buffers = {}
        self._user_chunk_counters = {}
        self._user_temp_recording_ids = {}
        self._user_bytes_read = {}

        await self.services.logging_service.info(
            f"Started recording session for meeting {self.meeting_id}, "
            f"user {self.user_id}, channel {self.channel_id}"
        )

        # Start Pycord recording with WaveSink
        self._sink = discord.sinks.WaveSink()

        # Start recording (callback will be triggered on stop)
        # Use sync_start=False to avoid blocking the event loop
        self.discord_voice_client.start_recording(
            self._sink, self._recording_finished_callback, sync_start=False
        )

        # Start periodic flush task for ALL users
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop_recording(self) -> None:
        """Stop the recording session and flush any remaining data for all users."""
        if not self.is_recording:
            return

        # Stop recording flag first
        self.is_recording = False

        # Cancel flush task
        if self._flush_task:
            self._flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._flush_task

        # Stop Pycord recording
        if self.discord_voice_client.recording:
            self.discord_voice_client.stop_recording()

        # Extract any final audio data from sink before flushing
        await self._extract_user_audio_from_sink()

        # Final flush of any remaining data for ALL users (regardless of buffer length)
        await self._flush_all_users(force=True)

        # Now set shutdown flag to prevent any new operations
        self._is_shutting_down = True

        total_chunks = sum(len(ids) for ids in self._user_temp_recording_ids.values())
        await self.services.logging_service.info(
            f"Stopped recording session for meeting {self.meeting_id}. "
            f"Created {total_chunks} temp recording chunks across {len(self._user_audio_buffers)} users."
        )

    # -------------------------------------------------------------- #
    # Audio Buffering Methods
    # -------------------------------------------------------------- #

    async def _recording_finished_callback(self, _sink: "discord.sinks.WaveSink", *_args) -> None:
        """
        Callback triggered when Pycord stops recording.

        This is primarily for final cleanup - the periodic flush task handles
        most of the audio processing during active recording.

        Args:
            _sink: The WaveSink containing per-user audio data (unused - periodic flush handles this)
            _args: Additional callback arguments (unused)
        """
        await self.services.logging_service.info(
            f"Recording finished callback for meeting {self.meeting_id}"
        )

    async def _extract_user_audio_from_sink(self) -> None:
        """
        Extract audio data from the Pycord sink for all users.

        This reads from sink.audio_data and appends new PCM data to per-user buffers.
        The sink accumulates audio continuously, so we track what we've already
        processed (via _user_bytes_read) to avoid duplicates.

        Note: WaveSink stores data as WAV format (44-byte header + PCM data).
        We skip the header on first read and only extract raw PCM thereafter.
        """
        if not self._sink or not self._sink.audio_data:
            return

        # WAV header size (standard RIFF WAV format)
        WAV_HEADER_SIZE = 44

        # Iterate through all users in the sink
        for user_id, audio_data in self._sink.audio_data.items():
            # Initialize buffer for new users
            if user_id not in self._user_audio_buffers:
                self._user_audio_buffers[user_id] = bytearray()
                self._user_chunk_counters[user_id] = 0
                self._user_temp_recording_ids[user_id] = []
                self._user_bytes_read[user_id] = 0

                await self.services.logging_service.info(
                    f"Started recording for user {user_id} in meeting {self.meeting_id}"
                )

            # Get current position in the BytesIO
            bytes_io = audio_data.file
            bytes_io.seek(0, 2)  # Seek to end to get total size
            total_bytes = bytes_io.tell()

            # Calculate how many new bytes are available
            bytes_already_read = self._user_bytes_read[user_id]
            new_bytes_available = total_bytes - bytes_already_read

            if new_bytes_available <= 0:
                continue  # No new data for this user

            # Seek to where we left off
            bytes_io.seek(bytes_already_read)

            # If this is the first read, skip WAV header
            if bytes_already_read == 0:
                # Skip WAV header (44 bytes)
                bytes_io.seek(WAV_HEADER_SIZE)
                bytes_already_read = WAV_HEADER_SIZE
                new_bytes_available = total_bytes - WAV_HEADER_SIZE

            # Read only the new PCM data
            new_pcm_data = bytes_io.read(new_bytes_available)

            # Append to user's buffer
            self._user_audio_buffers[user_id].extend(new_pcm_data)

            # Update bytes read tracker
            self._user_bytes_read[user_id] = total_bytes

    # -------------------------------------------------------------- #
    # Flush Cycle (Core Integration Point)
    # -------------------------------------------------------------- #

    async def _flush_loop(self) -> None:
        """
        Periodic flush loop that processes audio for ALL users.

        Runs every FLUSH_INTERVAL_SECONDS and:
        1. Extracts audio from Pycord sink
        2. Flushes audio for each user with buffered data
        """
        try:
            while self.is_recording and not self._is_shutting_down:
                await asyncio.sleep(DiscordRecorderConstants.FLUSH_INTERVAL_SECONDS)

                # Extract latest audio from sink
                await self._extract_user_audio_from_sink()

                # Flush all users
                await self._flush_all_users()

        except asyncio.CancelledError:
            await self.services.logging_service.debug("Flush loop cancelled")
            raise

    async def _flush_all_users(self, force: bool = False) -> None:
        """
        Flush audio data for all users who have buffered audio.

        For each user:
        1. Write PCM to temp storage
        2. Create temp recording in SQL
        3. Queue FFmpeg transcode job
        4. Clear buffer

        Args:
            force: If True, bypass shutdown check and flush all buffers regardless of length
        """
        if self._is_shutting_down and not force:
            return

        for user_id, buffer in list(self._user_audio_buffers.items()):
            if len(buffer) == 0:
                continue

            await self._flush_user(user_id, buffer)

    async def _flush_user(self, user_id: int, buffer: bytearray) -> None:
        """
        Flush audio buffer for a single user.

        Args:
            user_id: Discord user ID
            buffer: Audio buffer to flush
        """
        # Generate unique chunk filename
        chunk_num = self._user_chunk_counters[user_id]
        pcm_filename = f"{self.meeting_id}_user{user_id}_chunk{chunk_num:04d}.pcm"

        # Write PCM to temp storage
        pcm_path = await self._write_pcm_to_temp(pcm_filename, bytes(buffer))

        # Generate MP3 path
        mp3_path = pcm_path.replace(".pcm", ".mp3")

        # Create temp recording in SQL
        temp_recording_id = None
        if self.services.sql_recording_service_manager:
            try:
                temp_recording_id = (
                    await self.services.sql_recording_service_manager.insert_temp_recording(
                        user_id=str(user_id),  # Discord user ID, not bot user
                        meeting_id=self.meeting_id,
                        start_timestamp_ms=0,  # TODO: Calculate actual timestamp
                        filename=pcm_filename,
                    )
                )

                if temp_recording_id:
                    self._user_temp_recording_ids[user_id].append(temp_recording_id)
            except Exception as e:
                await self.services.logging_service.error(
                    f"CRITICAL DISCORD RECORDER SQL ERROR: Failed to create temp recording - "
                    f"Meeting: {self.meeting_id}, User: {user_id}, Chunk: {chunk_num}, "
                    f"Filename: {pcm_filename}, Error Type: {type(e).__name__}, Details: {str(e)}. "
                    f"This likely indicates a missing meeting entry in the meetings table (foreign key constraint)."
                )
                # Don't raise - allow recording to continue even if SQL fails
                # The file was already saved, so we can manually recover later

        # Queue FFmpeg transcode job
        await self._queue_pcm_to_mp3_transcode(pcm_path, mp3_path, temp_recording_id)

        # Clear buffer and increment counter
        buffer.clear()
        self._user_chunk_counters[user_id] += 1

        await self.services.logging_service.debug(
            f"Flushed chunk {chunk_num} for user {user_id} in meeting {self.meeting_id}"
        )

    # -------------------------------------------------------------- #
    # File Operations
    # -------------------------------------------------------------- #

    async def _write_pcm_to_temp(self, filename: str, data: bytes) -> str:
        """
        Write PCM data to temporary storage.

        Args:
            filename: PCM filename
            data: Raw PCM bytes

        Returns:
            Absolute path to the written PCM file
        """
        if not self.services.recording_file_service_manager:
            raise RuntimeError("Recording file manager service not available")

        try:
            # Write to temp storage
            file_path = await self.services.recording_file_service_manager.save_to_temp_file(
                filename=filename, data=data
            )
            return file_path
        except Exception as e:
            await self.services.logging_service.error(
                f"CRITICAL DISCORD RECORDER ERROR: Failed to write PCM to temp - "
                f"Meeting: {self.meeting_id}, Filename: {filename}, Size: {len(data)} bytes, "
                f"Error Type: {type(e).__name__}, Details: {str(e)}"
            )
            raise

    # -------------------------------------------------------------- #
    # FFmpeg Integration
    # -------------------------------------------------------------- #

    async def _queue_pcm_to_mp3_transcode(
        self, pcm_path: str, mp3_path: str, temp_recording_id: str | None
    ) -> None:
        """
        Queue a PCM → MP3 transcode job with temp recording tracking.

        Args:
            pcm_path: Path to PCM file
            mp3_path: Path to output MP3 file
            temp_recording_id: Optional temp recording ID for SQL tracking
        """
        if not self.services.ffmpeg_service_manager:
            await self.services.logging_service.warning(
                "FFmpeg manager service not available, skipping transcode"
            )
            return

        # Define callback to update SQL status
        async def on_transcode_complete(success: bool) -> None:
            if not self.services.sql_recording_service_manager or not temp_recording_id:
                return

            new_status = TranscodeStatus.DONE if success else TranscodeStatus.FAILED
            await self.services.sql_recording_service_manager.update_temp_recording_status(
                temp_recording_id=temp_recording_id, status=new_status
            )

            # Delete PCM file after successful transcode (non-blocking)
            if success and os.path.exists(pcm_path):
                try:
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, os.remove, pcm_path)
                except (OSError, PermissionError) as e:
                    await self.services.logging_service.warning(
                        f"Failed to delete PCM file {pcm_path}: {e}"
                    )

        # Queue FFmpeg job
        await self.services.ffmpeg_service_manager.queue_pcm_to_mp3(
            input_path=pcm_path,
            output_path=mp3_path,
            bitrate=DiscordRecorderConstants.MP3_BITRATE,
            callback=on_transcode_complete,
        )

    # -------------------------------------------------------------- #
    # Session Information Methods
    # -------------------------------------------------------------- #

    def get_temp_recording_ids(self) -> list[str]:
        """Get all temp recording IDs created during this session (across all users)."""
        all_ids = []
        for user_ids in self._user_temp_recording_ids.values():
            all_ids.extend(user_ids)
        return all_ids

    def get_recorded_user_ids(self) -> list[int]:
        """Get list of Discord user IDs that have been recorded in this session."""
        return list(self._user_audio_buffers.keys())

    async def get_session_status(self) -> dict:
        """Get current session status including per-user SQL tracking info."""
        # Check if SQL recording service is available
        if not self.services.sql_recording_service_manager:
            return {
                "is_recording": self.is_recording,
                "meeting_id": self.meeting_id,
                "user_id": self.user_id,
                "guild_id": self.guild_id,
                "channel_id": self.channel_id,
                "total_users": len(self._user_audio_buffers),
                "total_chunks": sum(len(ids) for ids in self._user_temp_recording_ids.values()),
                "per_user_stats": {
                    str(uid): {
                        "chunks": len(self._user_temp_recording_ids.get(uid, [])),
                        "buffer_size_bytes": len(self._user_audio_buffers.get(uid, bytearray())),
                    }
                    for uid in self._user_audio_buffers
                },
                "chunk_statuses": {"note": "SQL service not available"},
            }

        # Query SQL for chunk statuses
        chunks = await self.services.sql_recording_service_manager.get_temp_recordings_for_meeting(
            self.meeting_id
        )

        # Count by status (optimized with Counter)
        status_counter = Counter(c["transcode_status"] for c in chunks)
        status_counts = {
            "queued": status_counter.get(TranscodeStatus.QUEUED.value, 0),
            "in_progress": status_counter.get(TranscodeStatus.IN_PROGRESS.value, 0),
            "done": status_counter.get(TranscodeStatus.DONE.value, 0),
            "failed": status_counter.get(TranscodeStatus.FAILED.value, 0),
        }

        # Per-user statistics
        per_user_stats = {}
        for user_id in self._user_audio_buffers:
            user_chunks = [
                c for c in chunks if c["id"] in self._user_temp_recording_ids.get(user_id, [])
            ]
            user_status_counter = Counter(c["transcode_status"] for c in user_chunks)

            per_user_stats[str(user_id)] = {
                "chunks": len(self._user_temp_recording_ids.get(user_id, [])),
                "buffer_size_bytes": len(self._user_audio_buffers.get(user_id, bytearray())),
                "transcode_status": {
                    "queued": user_status_counter.get(TranscodeStatus.QUEUED.value, 0),
                    "in_progress": user_status_counter.get(TranscodeStatus.IN_PROGRESS.value, 0),
                    "done": user_status_counter.get(TranscodeStatus.DONE.value, 0),
                    "failed": user_status_counter.get(TranscodeStatus.FAILED.value, 0),
                },
            }

        return {
            "is_recording": self.is_recording,
            "meeting_id": self.meeting_id,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "total_users": len(self._user_audio_buffers),
            "total_chunks": sum(len(ids) for ids in self._user_temp_recording_ids.values()),
            "per_user_stats": per_user_stats,
            "chunk_statuses": status_counts,
        }


class DiscordRecorderManagerService(BaseDiscordRecorderServiceManager):
    """
    Manager for Discord Recorder Service.

    This class manages:
    - Multiple recording sessions
    - Session lifecycle (start, stop, pause, resume)
    - Promotion of temp recordings to persistent storage
    - Background cleanup of old temp records
    """

    def __init__(self, server: ServerManager):
        super().__init__(server)

        self.sessions: dict[int, DiscordSessionHandler] = {}
        self._cleanup_task: asyncio.Task | None = None

    # -------------------------------------------------------------- #
    # Discord Recorder Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services_manager: "ServicesManager") -> None:
        """Initialize the Discord Recorder Service Manager."""
        await super().on_start(services_manager)
        await self.services.logging_service.info("Discord Recorder Service Manager started")

        # Start background cleanup task for old temp recordings
        if self.services.sql_recording_service_manager:
            self._cleanup_task = asyncio.create_task(self._cleanup_old_temp_recordings())

    async def on_close(self) -> bool:
        """Stop the Discord Recorder Service Manager."""
        # Stop all active sessions
        for channel_id in list(self.sessions.keys()):
            await self.stop_session(channel_id)

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task

        await self.services.logging_service.info("Discord Recorder Service Manager stopped")
        return True

    # -------------------------------------------------------------- #
    # Session Management Methods
    # -------------------------------------------------------------- #

    async def start_session(
        self,
        discord_voice_client: discord.VoiceClient,
        channel_id: int,
        meeting_id: str | None = None,
        user_id: str | None = None,
        guild_id: str | None = None,
    ) -> bool:
        """
        Start recording audio from a Discord channel.

        Args:
            discord_voice_client: Active VoiceClient connected to the channel
            channel_id: Discord channel ID
            meeting_id: Optional meeting ID (generated if not provided)
            user_id: Optional Discord user ID (required for SQL tracking)
            guild_id: Optional Discord guild ID (required for SQL tracking)

        Returns:
            True if session started successfully
        """
        if channel_id in self.sessions:
            await self.services.logging_service.warning(
                f"Session already exists for channel {channel_id}"
            )
            return False

        # Generate meeting ID if not provided
        if not meeting_id:
            meeting_id = generate_16_char_uuid()

        # Validate required fields for SQL tracking
        if not user_id or not guild_id:
            await self.services.logging_service.error(
                "user_id and guild_id are required for SQL tracking"
            )
            return False

        # Create meeting entry in SQL database (CRITICAL: must happen before session starts)
        if self.services.sql_recording_service_manager:
            try:
                await self.services.sql_recording_service_manager.insert_meeting(
                    meeting_id=meeting_id,
                    guild_id=guild_id,
                    channel_id=str(channel_id),
                    requested_by=user_id,
                )
                await self.services.logging_service.info(
                    f"Created meeting entry in database: {meeting_id}"
                )
            except Exception as e:
                await self.services.logging_service.error(
                    f"CRITICAL ERROR: Failed to create meeting entry in database - "
                    f"Meeting: {meeting_id}, Guild: {guild_id}, Channel: {channel_id}, "
                    f"Error Type: {type(e).__name__}, Details: {str(e)}. "
                    f"Cannot start recording session without meeting entry (foreign key constraint)."
                )
                return False

        # Create session handler
        session = DiscordSessionHandler(
            discord_voice_client=discord_voice_client,
            channel_id=channel_id,
            meeting_id=meeting_id,
            user_id=user_id,
            guild_id=guild_id,
            services=self.services,
        )

        # Start recording
        await session.start_recording()

        # Store session
        self.sessions[channel_id] = session

        await self.services.logging_service.info(
            f"Started recording session for meeting {meeting_id}, channel {channel_id}"
        )
        return True

    async def stop_session(self, channel_id: int) -> bool:
        """
        Stop recording audio from a Discord channel and promote temp recordings.

        Steps:
        1. Stop recording session
        2. Wait for pending transcodes to complete
        3. Promote temp recordings to persistent storage
        4. Cleanup session

        Args:
            channel_id: Discord channel ID

        Returns:
            True if session stopped successfully
        """
        session = self.sessions.get(channel_id)
        if not session:
            await self.services.logging_service.warning(
                f"No active session for channel {channel_id}"
            )
            return False

        meeting_id = session.meeting_id
        user_id = session.user_id

        await self.services.logging_service.info(
            f"Stopping recording session for meeting {meeting_id}"
        )

        # Stop recording
        await session.stop_recording()

        # Wait for pending transcodes
        if self.services.sql_recording_service_manager:
            await self.services.logging_service.info(
                f"Waiting for pending transcodes for meeting {meeting_id}..."
            )

            completed = await self._wait_for_pending_transcodes(
                meeting_id=meeting_id,
                max_wait_seconds=DiscordRecorderConstants.TRANSCODE_TIMEOUT_SECONDS,
            )

            if not completed:
                await self.services.logging_service.warning(
                    f"Timeout waiting for transcodes on meeting {meeting_id}"
                )

            # Note: Temp recordings remain in temp storage and SQL
            # They will be cleaned up by the background cleanup task
            await self.services.logging_service.info(
                f"Recording session complete for meeting {meeting_id}. "
                f"Files are in temp storage and will be cleaned up after {DiscordRecorderConstants.TEMP_RECORDING_TTL_HOURS} hours."
            )

        # Cleanup session
        del self.sessions[channel_id]

        await self.services.logging_service.info(f"Stopped recording in channel {channel_id}")
        return True

    async def pause_session(self, channel_id: int) -> bool:
        """
        Pause an ongoing recording session.

        Args:
            channel_id: Discord channel ID

        Returns:
            True if session paused successfully
        """
        session = self.sessions.get(channel_id)
        if not session:
            await self.services.logging_service.warning(
                f"No active session for channel {channel_id}"
            )
            return False

        # Pause recording (stop flush cycle but keep session alive)
        session.is_recording = False
        if session._flush_task:
            session._flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await session._flush_task

        await self.services.logging_service.info(
            f"Paused recording session for channel {channel_id}"
        )
        return True

    async def resume_session(self, channel_id: int) -> bool:
        """
        Resume a paused recording session.

        Args:
            channel_id: Discord channel ID

        Returns:
            True if session resumed successfully
        """
        session = self.sessions.get(channel_id)
        if not session:
            await self.services.logging_service.warning(
                f"No active session for channel {channel_id}"
            )
            return False

        # Resume recording
        if not session.is_recording:
            session.is_recording = True
            session._flush_task = asyncio.create_task(session._flush_loop())

        await self.services.logging_service.info(
            f"Resumed recording session for channel {channel_id}"
        )
        return True

    # -------------------------------------------------------------- #
    # Global Cache Query Methods
    # -------------------------------------------------------------- #

    def get_active_session(self, channel_id: int) -> DiscordSessionHandler | None:
        """
        Get an active recording session by channel ID.

        Args:
            channel_id: Discord channel ID

        Returns:
            DiscordSessionHandler if session exists, None otherwise
        """
        return self.sessions.get(channel_id)

    def get_all_active_sessions(self) -> dict[int, DiscordSessionHandler]:
        """
        Get all active recording sessions.

        Returns:
            Dictionary mapping channel_id to DiscordSessionHandler
        """
        return self.sessions.copy()

    def is_recording_in_channel(self, channel_id: int) -> bool:
        """
        Check if there's an active recording session in a channel.

        Args:
            channel_id: Discord channel ID

        Returns:
            True if recording, False otherwise
        """
        session = self.sessions.get(channel_id)
        return session is not None and session.is_recording

    def get_session_by_guild(self, guild_id: str) -> list[DiscordSessionHandler]:
        """
        Get all active recording sessions in a specific guild.

        Args:
            guild_id: Discord guild ID (as string)

        Returns:
            List of DiscordSessionHandler objects
        """
        return [session for session in self.sessions.values() if session.guild_id == guild_id]

    def get_session_by_meeting_id(self, meeting_id: str) -> DiscordSessionHandler | None:
        """
        Get a recording session by meeting ID.

        Args:
            meeting_id: Meeting ID

        Returns:
            DiscordSessionHandler if found, None otherwise
        """
        for session in self.sessions.values():
            if session.meeting_id == meeting_id:
                return session
        return None

    async def get_session_stats(self, channel_id: int) -> dict | None:
        """
        Get statistics for a recording session.

        Args:
            channel_id: Discord channel ID

        Returns:
            Dictionary with session stats, or None if session not found
        """
        session = self.sessions.get(channel_id)
        if not session:
            return None

        return await session.get_stats()

    async def get_all_sessions_stats(self) -> dict[int, dict]:
        """
        Get statistics for all active recording sessions.

        Returns:
            Dictionary mapping channel_id to session stats
        """
        stats = {}
        for channel_id, session in self.sessions.items():
            stats[channel_id] = await session.get_stats()
        return stats

    # -------------------------------------------------------------- #
    # Promotion Helper Methods
    # -------------------------------------------------------------- #

    async def _wait_for_pending_transcodes(
        self,
        meeting_id: str,
        max_wait_seconds: int = DiscordRecorderConstants.TRANSCODE_TIMEOUT_SECONDS,
    ) -> bool:
        """
        Wait for all temp recordings to reach DONE or FAILED status.
        Uses exponential backoff for efficiency.

        Args:
            meeting_id: Meeting ID to check
            max_wait_seconds: Maximum time to wait

        Returns:
            True if all transcodes completed, False if timeout
        """
        start_time = datetime.utcnow()
        poll_interval = 1  # Start with 1 second
        max_poll_interval = 10  # Cap at 10 seconds

        while True:
            # Query temp recordings for the meeting
            chunks = (
                await self.services.sql_recording_service_manager.get_temp_recordings_for_meeting(
                    meeting_id
                )
            )

            # Check for pending transcodes using enum values
            pending = [
                c
                for c in chunks
                if c["transcode_status"]
                in [TranscodeStatus.QUEUED.value, TranscodeStatus.IN_PROGRESS.value]
            ]

            if not pending:
                await self.services.logging_service.info(
                    f"All transcodes completed for meeting {meeting_id}"
                )
                return True

            # Check timeout
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed > max_wait_seconds:
                await self.services.logging_service.warning(
                    f"Timeout waiting for {len(pending)} transcodes on meeting {meeting_id}"
                )
                return False

            # Log progress every 10 seconds
            if int(elapsed) % 10 == 0:
                await self.services.logging_service.debug(
                    f"Waiting for {len(pending)} transcodes (elapsed: {int(elapsed)}s)"
                )

            await asyncio.sleep(poll_interval)
            # Exponential backoff
            poll_interval = min(poll_interval * 1.5, max_poll_interval)

    # -------------------------------------------------------------- #
    # Background Cleanup Methods
    # -------------------------------------------------------------- #

    async def _cleanup_old_temp_recordings(self) -> None:
        """
        Background task to clean up old temp recordings.

        This runs periodically to delete temp recordings older than a TTL.
        """
        cleanup_interval = DiscordRecorderConstants.CLEANUP_INTERVAL_SECONDS
        ttl_hours = DiscordRecorderConstants.TEMP_RECORDING_TTL_HOURS

        await self.services.logging_service.info(
            f"Started temp recording cleanup task (TTL: {ttl_hours}h, interval: {cleanup_interval}s)"
        )

        try:
            while True:
                await asyncio.sleep(cleanup_interval)

                try:
                    await self._cleanup_old_temp_recordings_once(ttl_hours)
                except Exception as e:
                    await self.services.logging_service.error(
                        f"Error during temp recording cleanup: {e}"
                    )

        except asyncio.CancelledError:
            await self.services.logging_service.info("Cleanup task cancelled")

    async def _cleanup_old_temp_recordings_once(self, ttl_hours: int) -> None:
        """
        Run a single cleanup cycle.

        Args:
            ttl_hours: Delete temp recordings older than this many hours
        """
        cutoff_time = datetime.utcnow() - timedelta(hours=ttl_hours)

        # Query old temp recordings using enum values
        query = """
            SELECT id, mp3_path, pcm_path
            FROM temp_recordings
            WHERE created_at < :cutoff
            AND transcode_status IN (:status_done, :status_failed)
        """
        params = {
            "cutoff": cutoff_time,
            "status_done": TranscodeStatus.DONE.value,
            "status_failed": TranscodeStatus.FAILED.value,
        }

        old_recordings = await self.server.sql_client.query(query, params)

        if not old_recordings:
            await self.services.logging_service.debug("No old temp recordings to clean up")
            return

        await self.services.logging_service.info(
            f"Found {len(old_recordings)} old temp recordings to clean up"
        )

        # Delete files and SQL records
        deleted_count = 0
        for record in old_recordings:
            temp_id = record["id"]
            mp3_path = record.get("mp3_path")
            pcm_path = record.get("pcm_path")

            try:
                loop = asyncio.get_event_loop()

                # Delete MP3 file if exists (non-blocking)
                if mp3_path and os.path.exists(mp3_path):
                    await loop.run_in_executor(None, os.remove, mp3_path)

                # Delete PCM file if exists (non-blocking)
                if pcm_path and os.path.exists(pcm_path):
                    await loop.run_in_executor(None, os.remove, pcm_path)

                deleted_count += 1

                await self.services.logging_service.debug(
                    f"Cleaned up temp recording files: {temp_id}"
                )

            except (OSError, PermissionError) as e:
                await self.services.logging_service.error(
                    f"Failed to clean up temp recording {temp_id}: {e}"
                )

        # Delete SQL records in batches
        if deleted_count > 0:
            temp_ids = [r["id"] for r in old_recordings[:deleted_count]]
            await self._delete_temp_recordings_batch(temp_ids)

        await self.services.logging_service.info(
            f"Cleanup completed: {deleted_count} temp recordings removed"
        )

    async def _delete_temp_recordings_batch(self, temp_ids: list[str]) -> None:
        """
        Delete temp recordings in batches to avoid SQL parameter limits.

        Args:
            temp_ids: List of temp recording IDs to delete
        """
        batch_size = DiscordRecorderConstants.MAX_DELETE_BATCH_SIZE

        for i in range(0, len(temp_ids), batch_size):
            batch = temp_ids[i : i + batch_size]
            try:
                await self.services.sql_recording_service_manager.delete_temp_recordings(batch)
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to delete batch of {len(batch)} temp recordings: {e}"
                )

    # -------------------------------------------------------------- #
    # Session Information Methods
    # -------------------------------------------------------------- #

    async def get_session_status(self, channel_id: int) -> dict | None:
        """
        Get status for a specific session.

        Args:
            channel_id: Discord channel ID

        Returns:
            Session status dictionary or None if session not found
        """
        session = self.sessions.get(channel_id)
        if not session:
            return None

        return await session.get_session_status()

    async def list_active_sessions(self) -> list[dict]:
        """
        List all active recording sessions.

        Returns:
            List of session status dictionaries
        """
        sessions = []
        for channel_id, session in self.sessions.items():
            status = await session.get_session_status()
            sessions.append(status)

        return sessions
