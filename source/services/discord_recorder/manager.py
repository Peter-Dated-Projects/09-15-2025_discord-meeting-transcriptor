import asyncio
import os
from collections import Counter
from contextlib import suppress
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from sqlalchemy import select

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import MeetingStatus, TempRecordingModel, TranscodeStatus
from source.services.discord_recorder.pcm_generator import (
    SilentPCM,
    calculate_pcm_duration_ms,
)
from source.services.manager import BaseDiscordRecorderServiceManager, ServicesManager
from source.utils import BotUtils, generate_16_char_uuid, get_current_timestamp_est

# -------------------------------------------------------------- #
# Configuration Constants
# -------------------------------------------------------------- #


class DiscordRecorderConstants:
    """Configuration constants for Discord recording."""

    # Discord audio format (from Pycord WaveSink and Opus specs)
    # These match Discord's internal audio format as documented in discord.opus._OpusStruct
    DISCORD_SAMPLE_RATE = 48000  # 48 kHz
    DISCORD_BITS_PER_SAMPLE = 16  # 16-bit signed PCM
    DISCORD_CHANNELS = 2  # Stereo
    DISCORD_UNSIGNED_8BIT = False  # Signed PCM

    # Timeline-driven chunker constants
    # Discord sends ~20ms frames; maintain frame alignment to avoid clicks
    FRAME_MS = 20  # Discord packet frame duration in milliseconds
    BYTES_PER_SAMPLE = DISCORD_BITS_PER_SAMPLE // 8  # 2 bytes for 16-bit
    BYTES_PER_MS = (
        DISCORD_SAMPLE_RATE * DISCORD_CHANNELS * BYTES_PER_SAMPLE // 1000
    )  # 192 bytes per ms
    FRAME_BYTES = BYTES_PER_MS * FRAME_MS  # 3840 bytes per 20ms frame
    WINDOW_MS = 30_000  # Exact 30 second windows in milliseconds
    WINDOW_BYTES = BYTES_PER_MS * WINDOW_MS  # 5,760,000 bytes per 30s window

    # Flush cycle
    # Note: keep flush at 30 seconds. Flush determines our grace period for empty call times
    #       before we consider the call ended. Shorter intervals increase DB load.
    #       Longer intervals may delay the end of the call.
    # FLUSH_INTERVAL_SECONDS = 30  # Configurable: flush buffer every N seconds
    FLUSH_INTERVAL_SECONDS = 15  # Configurable: flush buffer every N seconds

    # Empty call detection
    # After this many consecutive empty flush cycles, automatically stop recording
    # Empty = no users in channel except bot, or no audio data
    # Example: 2 cycles * 30 seconds = 60 seconds grace period
    EMPTY_CALL_FLUSH_CYCLES_THRESHOLD = 2

    # Maximum recording duration
    # Forcibly stop recording after this many seconds to prevent excessive resource usage
    # 5 hours = 18000 seconds
    MAX_RECORDING_DURATION_SECONDS = 18000  # 5 hours

    # FFmpeg encoding
    MP3_BITRATE = "128k"  # 128 kbps

    # Transcode timeout
    TRANSCODE_TIMEOUT_SECONDS = 360  # 6 minutes

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
        context: "Context",
    ):
        self.discord_voice_client = discord_voice_client
        self.channel_id = channel_id
        self.meeting_id = meeting_id
        self.user_id = user_id  # Bot user ID (for SQL tracking)
        self.guild_id = guild_id
        self.context = context
        # Backward compatibility
        self.services = context.services_manager
        self.start_time = get_current_timestamp_est()
        self.is_recording = False
        self.is_paused = False  # Track if session is paused
        self.pause_time: datetime | None = None  # Track when session was paused

        # Per-user audio buffers: {user_id: bytearray}
        self._user_audio_buffers: dict[int, bytearray] = {}

        # Track chunk counters per user: {user_id: int}
        self._user_chunk_counters: dict[int, int] = {}

        # Track temp recording IDs per user: {user_id: list[str]}
        self._user_temp_recording_ids: dict[int, list[str]] = {}

        # Track how many bytes we've read from each user's sink: {user_id: int}
        self._user_bytes_read: dict[int, int] = {}

        # Timeline tracking per user (wall-clock based, in milliseconds)
        # Tracks the wall-clock time of the last PCM write for gap detection
        self._user_last_wall_ms: dict[int, int] = {}

        # Silent PCM generator for gap padding
        self._silent_gen = SilentPCM(
            sample_rate=DiscordRecorderConstants.DISCORD_SAMPLE_RATE,
            bits_per_sample=DiscordRecorderConstants.DISCORD_BITS_PER_SAMPLE,
            channels=DiscordRecorderConstants.DISCORD_CHANNELS,
            unsigned_8bit=DiscordRecorderConstants.DISCORD_UNSIGNED_8BIT,
        )

        # Pycord recording sink
        self._sink: discord.sinks.WaveSink | None = None

        # Shutdown flag
        self._is_shutting_down = False

        self._flush_task: asyncio.Task | None = None

        # Empty call detection
        self._consecutive_empty_flush_cycles = 0
        self._empty_call_notification_sent = False  # Track if we've sent the empty call DM

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
        self._user_last_wall_ms = {}

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
        # If already shutdown, do nothing
        if self._is_shutting_down:
            return

        # If paused, we still need to do cleanup, so don't return early
        # Only return if not recording AND not paused (meaning already stopped)
        if not self.is_recording and not self.is_paused:
            return

        # Determine if we were paused (audio already flushed to temp files during pause)
        was_paused = self.is_paused

        # Stop recording flag first
        self.is_recording = False
        self.is_paused = False  # Clear paused flag on stop

        # Cancel flush task (might already be cancelled if paused)
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._flush_task

        # Stop Pycord recording
        if self.discord_voice_client.recording:
            self.discord_voice_client.stop_recording()

        # Only extract and flush if we weren't paused
        # (when paused, audio has already been flushed to temp files)
        if not was_paused:
            # Extract any final audio data from sink before flushing
            await self._extract_user_audio_from_sink()

            # Final flush of any remaining data for ALL users (regardless of buffer length)
            await self._flush_all_users(force=True)

            # Final timeline catch-up: ensure all users have the same number of chunks
            # by padding stragglers to match the user with the most chunks
            await self._backfill_to_max_chunks()
        else:
            await self.services.logging_service.info(
                "Session was paused - skipping audio extraction/flush (audio already saved to temp files during pause)"
            )

        # Now set shutdown flag to prevent any new operations
        self._is_shutting_down = True

        total_chunks = sum(len(ids) for ids in self._user_temp_recording_ids.values())
        await self.services.logging_service.info(
            f"Stopped recording session for meeting {self.meeting_id}. "
            f"Created {total_chunks} temp recording chunks across {len(self._user_audio_buffers)} users."
        )

    async def pause_recording(self) -> None:
        """
        Pause the recording session and save all accumulated audio data to temp files.

        When paused:
        - Recording flag is set to False (stops flush cycle)
        - Flush task is cancelled
        - All audio accumulated UP TO the pause point is extracted and saved to temp files
        - Discord voice recording is STOPPED (no audio collected during pause)
        - Sink is cleared to release resources
        - All audio buffers are cleared after saving
        - Pause time is recorded for timeline adjustment on resume
        - is_paused flag is set to True

        Audio Handling:
        - Audio collected BEFORE pause: SAVED to temp files
        - Audio collected DURING pause: NONE (Discord recording stopped)

        This ensures clean data flow without silent gaps during paused periods.
        """
        if not self.is_recording:
            await self.services.logging_service.warning(
                f"Session {self.channel_id} is not currently recording"
            )
            return

        # Record the pause time BEFORE stopping recording
        self.pause_time = get_current_timestamp_est()

        # Stop the recording flag and cancel flush task
        self.is_recording = False
        if self._flush_task:
            self._flush_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._flush_task

        # Extract and flush audio data to temp files before pausing
        # This ensures temp recordings exist in database for later processing
        await self._extract_user_audio_from_sink()
        await self._flush_all_users(force=True)

        # Stop Discord recording to prevent audio collection during pause
        if self.discord_voice_client.recording:
            self.discord_voice_client.stop_recording()
            await self.services.logging_service.info(
                f"Stopped Discord voice recording for meeting {self.meeting_id}"
            )

        # Clear the sink to release resources
        self._sink = None

        # Clear buffers after flushing (audio is saved to temp files)
        await self._clear_audio_buffers()

        # Set paused flag
        self.is_paused = True

        total_chunks = sum(len(ids) for ids in self._user_temp_recording_ids.values())
        await self.services.logging_service.info(
            f"Paused recording session for meeting {self.meeting_id}, channel {self.channel_id}. "
            f"Saved {total_chunks} temp recording chunks to storage."
        )

    async def resume_recording(self) -> None:
        """
        Resume a paused recording session with fresh timeline synchronization.

        When resumed:
        1. Resets all tracking variables for a fresh start
        2. Adjusts start_time to account for the pause duration
        3. Restarts Discord voice recording with a fresh sink
        4. Restarts the recording flag and flush loop
        5. Clears the paused flag

        Audio Handling:
        - Audio collected DURING pause: NONE (Discord recording was stopped)
        - Audio collected AFTER resume: Recorded with correct timeline positioning

        Timeline Continuity:
        - start_time is adjusted forward by pause_duration
        - This makes the final recording continuous without the paused period
        - No silent gaps in the output audio files

        This ensures:
        - No audio data from the pause period (recording was stopped)
        - Timeline calculations are synced to the resume time
        - Clean, gap-free recordings without wasted storage
        """
        if not self.is_paused:
            await self.services.logging_service.warning(
                f"Session {self.channel_id} is not currently paused"
            )
            return

        if not self.pause_time:
            await self.services.logging_service.warning(
                f"Session {self.channel_id} has no recorded pause time"
            )
            return

        # Calculate pause duration
        current_time = get_current_timestamp_est()
        pause_duration = current_time - self.pause_time

        await self.services.logging_service.info(
            f"Resuming recording for meeting {self.meeting_id}. "
            f"Pause duration: {pause_duration.total_seconds():.2f} seconds"
        )

        # Adjust start_time forward by the pause duration
        # This makes the timeline continuous as if the pause never happened
        self.start_time = self.start_time + pause_duration

        await self.services.logging_service.info(
            f"Adjusted start_time forward by {pause_duration.total_seconds():.2f}s for timeline continuity"
        )

        # Clear sink audio data and reset tracking to start fresh
        await self._clear_sink_and_reset_tracking()

        # Reset empty call detection counter to prevent premature auto-stop after resume
        self._consecutive_empty_flush_cycles = 0

        # Restart Discord recording with a fresh sink
        self._sink = discord.sinks.WaveSink()
        self.discord_voice_client.start_recording(
            self._sink, self._recording_finished_callback, sync_start=False
        )
        await self.services.logging_service.info(
            f"Restarted Discord voice recording for meeting {self.meeting_id}"
        )

        # Restart recording
        self.is_recording = True
        self.is_paused = False
        self.pause_time = None
        self._flush_task = asyncio.create_task(self._flush_loop())

        await self.services.logging_service.info(
            f"Resumed recording session for meeting {self.meeting_id}, channel {self.channel_id}"
        )

    async def _clear_audio_buffers(self) -> None:
        """
        Clear all audio buffers after data has been flushed to temp files.

        This method only clears in-memory buffers. It does NOT discard sink data
        because the audio has already been extracted and saved to temp files.

        Called after pause to free memory while preserving saved recordings.
        """
        buffer_count = 0
        total_bytes_cleared = 0
        for user_id, buffer in self._user_audio_buffers.items():
            buffer_size = len(buffer)
            if buffer_size > 0:
                buffer_count += 1
                total_bytes_cleared += buffer_size
                buffer.clear()

        await self.services.logging_service.info(
            f"Cleared audio buffers for meeting {self.meeting_id}: "
            f"{buffer_count} user buffer(s) cleared, "
            f"{total_bytes_cleared:,} bytes freed ({total_bytes_cleared / 1024 / 1024:.2f} MB)"
        )

    async def _clear_sink_and_reset_tracking(self) -> None:
        """
        Reset all tracking variables for a fresh resume.

        Since Discord recording is stopped during pause and a fresh sink is created
        on resume, this method only needs to reset tracking variables.

        Tracking Reset:
        1. Resets _user_bytes_read to 0 for all users (preserves user entries)
        2. Clears _user_last_wall_ms entries (will be recalculated on next audio)

        This ensures that when recording resumes:
        - We start fresh with the new sink
        - Timeline system resyncs properly
        - Users are properly tracked without being treated as "new"
        """
        # Reset tracking variables for all users
        # Reset bytes_read to 0 (preserve entries so _extract_user_audio_from_sink doesn't treat them as new users)
        for user_id in self._user_bytes_read:
            self._user_bytes_read[user_id] = 0

        # Clear last_wall_ms (will be recalculated when next audio arrives)
        self._user_last_wall_ms.clear()

        await self.services.logging_service.info(
            f"Reset tracking variables for meeting {self.meeting_id}. "
            f"Ready for fresh resume with new sink."
        )

    # -------------------------------------------------------------- #
    # Audio Buffering Methods
    # -------------------------------------------------------------- #

    def _is_frame_aligned(self, num_bytes: int) -> bool:
        """
        Check if a given number of bytes is frame-aligned (multiple of 20ms frame size).

        Frame alignment is critical to avoid audio clicks and maintain proper timing.
        Discord sends ~20ms frames, so all audio chunks should be multiples of 3,840 bytes.

        Args:
            num_bytes: Number of PCM bytes to check

        Returns:
            True if num_bytes is a multiple of FRAME_BYTES (3,840), False otherwise
        """
        return num_bytes % DiscordRecorderConstants.FRAME_BYTES == 0

    def _is_call_empty(self) -> bool:
        """
        Check if the voice call is empty (no human users, only bot).

        A call is considered empty if:
        1. Voice client is not connected, OR
        2. No users in channel except the bot itself

        Returns:
            True if call is empty, False otherwise
        """
        if not self.discord_voice_client or not self.discord_voice_client.is_connected():
            return True

        # Get channel members
        channel = self.discord_voice_client.channel
        if not channel:
            return True

        # Count non-bot members
        human_members = [member for member in channel.members if not member.bot]

        return len(human_members) == 0

    def _has_exceeded_max_duration(self) -> bool:
        """
        Check if the recording has exceeded the maximum allowed duration.

        Returns:
            True if recording duration exceeds MAX_RECORDING_DURATION_SECONDS, False otherwise
        """
        if not self.start_time:
            return False

        # Calculate elapsed time
        current_time = get_current_timestamp_est()
        elapsed_seconds = (current_time - self.start_time).total_seconds()

        return elapsed_seconds >= DiscordRecorderConstants.MAX_RECORDING_DURATION_SECONDS

    def get_recording_duration_seconds(self) -> float:
        """
        Get the current recording duration in seconds.

        Returns:
            Duration in seconds since recording started
        """
        if not self.start_time:
            return 0.0

        current_time = get_current_timestamp_est()
        return (current_time - self.start_time).total_seconds()

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
        Extract audio data from the Pycord sink for all users with timeline-driven gap padding.

        This reads from sink.audio_data and appends new PCM data to per-user buffers.
        The sink accumulates audio continuously, so we track what we've already
        processed (via _user_bytes_read) to avoid duplicates.

        Timeline-driven architecture:
        1. Use session clock (elapsed time since start_time) for all timeline calculations
        2. On each new PCM block, detect gaps since last write
        3. Pad gaps with silence (rounded UP to 20ms frame boundaries)
        4. Maintain continuous timeline for exact 30s windowing

        First-packet-anchored backfill for new users:
        - Backfill whole 30s windows from session start to first packet start
        - Pad intra-window remainder (20ms aligned) before first audio
        - Set last_wall_ms to END of first packet for subsequent gap detection

        Session-clock gap padding for existing users:
        - Calculate packet_start_ms = session_ms - pcm_ms
        - Detect gaps: gap_ms = packet_start_ms - last_wall_ms
        - Pad silence rounded up to nearest 20ms frame
        - Update last_wall_ms to END of current packet

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
            is_new_user = user_id not in self._user_audio_buffers
            if is_new_user:
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

            # Calculate duration of this new PCM block in milliseconds
            pcm_ms = calculate_pcm_duration_ms(
                len(new_pcm_data),
                sample_rate=DiscordRecorderConstants.DISCORD_SAMPLE_RATE,
                bits_per_sample=DiscordRecorderConstants.DISCORD_BITS_PER_SAMPLE,
                channels=DiscordRecorderConstants.DISCORD_CHANNELS,
            )

            # **SESSION CLOCK**: Use elapsed time since recording start for all timeline math
            # This ensures consistent timeline regardless of system time changes
            session_ms = int((get_current_timestamp_est() - self.start_time).total_seconds() * 1000)
            packet_start_ms = max(0, session_ms - pcm_ms)

            # **NEW-USER FIRST-PACKET-ANCHORED BACKFILL**
            # Backfill from session start to the beginning of this first packet
            # Also applies to users resuming after pause (not in _user_last_wall_ms)
            if is_new_user or user_id not in self._user_last_wall_ms:
                # Backfill WHOLE windows up to just before packet_start_ms
                full_windows = packet_start_ms // DiscordRecorderConstants.WINDOW_MS

                if full_windows > 0:
                    await self.services.logging_service.info(
                        f"{'New' if is_new_user else 'Resuming'} user {user_id} at session t={session_ms}ms ({session_ms / 1000:.1f}s). "
                        f"First packet starts at t={packet_start_ms}ms. "
                        f"Backfilling {full_windows} silent window(s) for timeline alignment."
                    )

                    # Emit silent chunks for each elapsed window
                    for window_idx in range(full_windows):
                        await self._flush_user_backfill(
                            user_id=user_id,
                            chunk_idx=window_idx,
                        )
                        self._user_chunk_counters[user_id] += 1

                    await self.services.logging_service.info(
                        f"Backfill complete for user {user_id}: emitted {full_windows} silent window(s), "
                        f"next chunk will be {self._user_chunk_counters[user_id]}"
                    )

                # Pad intra-window remainder (time from last window boundary to packet start)
                # This ensures first audio lands at the correct timeline position within the window
                pre_gap_ms = packet_start_ms - (full_windows * DiscordRecorderConstants.WINDOW_MS)
                if pre_gap_ms > 0:
                    # Round up to 20ms frame boundaries
                    frames_needed = (
                        pre_gap_ms + DiscordRecorderConstants.FRAME_MS - 1
                    ) // DiscordRecorderConstants.FRAME_MS
                    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS

                    # Generate silence padding
                    silence_padding = self._silent_gen.generate(pad_ms)
                    self._user_audio_buffers[user_id].extend(silence_padding)

                    await self.services.logging_service.debug(
                        f"Intra-window pre-gap for user {user_id}: {pre_gap_ms}ms (rounded to {pad_ms}ms, {frames_needed} frames). "
                        f"Padded {len(silence_padding):,} bytes of silence before first PCM."
                    )

                # Append the first PCM block at the correct timeline position
                self._user_audio_buffers[user_id].extend(new_pcm_data)

                # Set last_wall_ms to the END of this first packet
                self._user_last_wall_ms[user_id] = packet_start_ms + pcm_ms

            else:
                # **EXISTING USER SESSION-CLOCK GAP PADDING**
                # Detect and fill gaps since last packet using session clock
                last_wall_ms = self._user_last_wall_ms[user_id]

                # Calculate gap: time between end of last packet and start of this packet
                gap_ms = max(0, packet_start_ms - last_wall_ms)

                # Pad silence for the gap (rounded up to frame boundaries)
                if gap_ms > 0:
                    # Round up to nearest 20ms frame boundary
                    frames_needed = (
                        gap_ms + DiscordRecorderConstants.FRAME_MS - 1
                    ) // DiscordRecorderConstants.FRAME_MS
                    pad_ms = frames_needed * DiscordRecorderConstants.FRAME_MS

                    # Generate silence padding
                    silence_padding = self._silent_gen.generate(pad_ms)

                    # Append padding to buffer
                    self._user_audio_buffers[user_id].extend(silence_padding)

                    await self.services.logging_service.debug(
                        f"Gap detected for user {user_id}: {gap_ms}ms (rounded to {pad_ms}ms, {frames_needed} frames). "
                        f"Padded {len(silence_padding):,} bytes of silence."
                    )

                # Append actual PCM data to user's buffer
                self._user_audio_buffers[user_id].extend(new_pcm_data)

                # Update timeline: set last_wall_ms to the END of this packet
                self._user_last_wall_ms[user_id] = packet_start_ms + pcm_ms

            # Update bytes read tracker
            self._user_bytes_read[user_id] = total_bytes

    # -------------------------------------------------------------- #
    # Flush Cycle (Core Integration Point)
    # -------------------------------------------------------------- #

    async def _send_empty_call_notification(self) -> None:
        """
        Send a DM to the user who requested the meeting about an empty call.

        This notifies them that the recording is still running but no users are in the call,
        and they should run /stop or wait for auto-cleanup.
        """
        try:
            # Check if bot instance is available
            if not self.context.bot:
                await self.services.logging_service.warning(
                    "Bot instance not available, cannot send empty call notification"
                )
                return

            # Get guild name from voice client
            guild_name = "the server"  # Default fallback
            if self.discord_voice_client and self.discord_voice_client.channel:
                channel = self.discord_voice_client.channel
                if hasattr(channel, "guild") and channel.guild:
                    guild_name = channel.guild.name

            # Construct message
            message = (
                f"Your meeting in **{guild_name}** is still running but there are no active users in the call. "
                f"Run `/stop` in the guild to stop the recording, or leave it and we'll clean it up in "
                f"{DiscordRecorderConstants.FLUSH_INTERVAL_SECONDS} seconds."
            )

            # Send DM to the user who requested the meeting
            success = await BotUtils.send_dm(self.context.bot, self.user_id, message)

            if success:
                await self.services.logging_service.info(
                    f"Sent empty call notification to user {self.user_id} for meeting {self.meeting_id}"
                )
            else:
                await self.services.logging_service.warning(
                    f"Failed to send empty call notification to user {self.user_id} for meeting {self.meeting_id}"
                )

        except Exception as e:
            # Catch all exceptions to prevent disrupting the flush loop
            await self.services.logging_service.error(
                f"Error sending empty call notification for meeting {self.meeting_id}: {e}"
            )

    async def _flush_loop(self) -> None:
        """
        Periodic flush loop that processes audio for ALL users.

        Runs every FLUSH_INTERVAL_SECONDS and:
        1. Extracts audio from Pycord sink
        2. Flushes audio for each user with buffered data
        3. Checks if call is empty and triggers auto-stop after threshold
        4. Checks if recording has exceeded maximum duration and triggers auto-stop
        """
        try:
            flush_count = 0
            while self.is_recording and not self._is_shutting_down:
                await asyncio.sleep(DiscordRecorderConstants.FLUSH_INTERVAL_SECONDS)
                flush_count += 1

                await self.services.logging_service.info(
                    f"Running flush cycle #{flush_count} for meeting {self.meeting_id} "
                    f"(interval: {DiscordRecorderConstants.FLUSH_INTERVAL_SECONDS}s)"
                )

                # Extract latest audio from sink
                await self._extract_user_audio_from_sink()

                # Check if recording has exceeded maximum duration
                if self._has_exceeded_max_duration():
                    duration_hours = self.get_recording_duration_seconds() / 3600
                    await self.services.logging_service.warning(
                        f"Recording for meeting {self.meeting_id} has exceeded maximum duration "
                        f"({duration_hours:.2f} hours). Forcibly stopping recording."
                    )
                    # Trigger auto-stop by breaking the loop
                    break

                # Check if call is empty (no human users)
                is_empty = self._is_call_empty()

                if is_empty:
                    self._consecutive_empty_flush_cycles += 1
                    await self.services.logging_service.info(
                        f"Empty call detected for meeting {self.meeting_id} "
                        f"(consecutive empty cycles: {self._consecutive_empty_flush_cycles}/"
                        f"{DiscordRecorderConstants.EMPTY_CALL_FLUSH_CYCLES_THRESHOLD})"
                    )

                    # Send notification on first empty cycle (only once)
                    if (
                        self._consecutive_empty_flush_cycles == 1
                        and not self._empty_call_notification_sent
                    ):
                        await self._send_empty_call_notification()
                        self._empty_call_notification_sent = True

                    # Check if we've exceeded the threshold
                    if (
                        self._consecutive_empty_flush_cycles
                        >= DiscordRecorderConstants.EMPTY_CALL_FLUSH_CYCLES_THRESHOLD
                    ):
                        await self.services.logging_service.info(
                            f"Call has been empty for {self._consecutive_empty_flush_cycles} consecutive cycles. "
                            f"Auto-stopping recording for meeting {self.meeting_id}."
                        )
                        # Trigger auto-stop by breaking the loop
                        # The stop_recording will be called by the manager
                        break
                else:
                    # Reset counter if call has users
                    if self._consecutive_empty_flush_cycles > 0:
                        await self.services.logging_service.info(
                            f"Call is active again for meeting {self.meeting_id}. "
                            f"Resetting empty cycle counter (was {self._consecutive_empty_flush_cycles})."
                        )
                    self._consecutive_empty_flush_cycles = 0
                    self._empty_call_notification_sent = (
                        False  # Reset notification flag when call is active again
                    )

                # Flush all users
                await self._flush_all_users()

                # Backfill absent users with silent windows to maintain timeline alignment
                # (runs AFTER flush so chunk counters are up-to-date)
                await self._backfill_absent_users()

                await self.services.logging_service.info(
                    f"Completed flush cycle #{flush_count} for meeting {self.meeting_id}"
                )

        except asyncio.CancelledError:
            await self.services.logging_service.debug("Flush loop cancelled")
            raise

    async def _flush_all_users(self, force: bool = False) -> None:
        """
        Flush audio data for all users using exact 30s windowing.

        For each user with buffered audio:
        1. Process buffer in exact WINDOW_BYTES (30s) increments
        2. Emit full windows immediately
        3. On final flush (force=True), emit remaining partial window WITHOUT padding
           (partial windows only occur at the very end of recording)

        Order in flush cycle: extract → flush → absent-user backfill

        Timeline-driven windowing ensures:
        - Each window is exactly 30,000ms (5,760,000 bytes)
        - Gaps are pre-filled with silence in _extract_user_audio_from_sink
        - Chunks align at exact 30s boundaries for downstream processing

        Args:
            force: If True, this is the final flush on stop_recording.
                   Emit any remaining partial windows without padding.

        Note: This method processes ONLY users with data in buffers.
              Absent users are handled separately by _backfill_absent_users().
        """
        if self._is_shutting_down and not force:
            return

        users_with_data = 0
        total_buffer_size = 0
        total_windows_emitted = 0

        for user_id, buffer in list(self._user_audio_buffers.items()):
            if len(buffer) == 0:
                continue

            users_with_data += 1
            total_buffer_size += len(buffer)

            # Process buffer in exact 30s windows
            windows_emitted = 0
            while len(buffer) >= DiscordRecorderConstants.WINDOW_BYTES:
                # Extract exact 30s window
                window_data = bytes(buffer[: DiscordRecorderConstants.WINDOW_BYTES])
                del buffer[: DiscordRecorderConstants.WINDOW_BYTES]

                # Validate frame alignment
                if not self._is_frame_aligned(len(window_data)):
                    await self.services.logging_service.warning(
                        f"Window {self._user_chunk_counters[user_id]} for user {user_id} "
                        f"is NOT frame-aligned: {len(window_data)} bytes "
                        f"(expected multiple of {DiscordRecorderConstants.FRAME_BYTES})"
                    )

                # Flush this exact 30s window
                await self._flush_user_window(
                    user_id=user_id,
                    chunk_idx=self._user_chunk_counters[user_id],
                    window_data=window_data,
                )

                self._user_chunk_counters[user_id] += 1
                windows_emitted += 1

            total_windows_emitted += windows_emitted

            # On final flush, emit remaining partial window (if any)
            if force and len(buffer) > 0:
                partial_window_data = bytes(buffer)
                buffer.clear()

                partial_duration_ms = calculate_pcm_duration_ms(
                    len(partial_window_data),
                    sample_rate=DiscordRecorderConstants.DISCORD_SAMPLE_RATE,
                    bits_per_sample=DiscordRecorderConstants.DISCORD_BITS_PER_SAMPLE,
                    channels=DiscordRecorderConstants.DISCORD_CHANNELS,
                )

                await self.services.logging_service.info(
                    f"Final flush: emitting partial window for user {user_id} - "
                    f"{len(partial_window_data):,} bytes ({partial_duration_ms}ms)"
                )

                # Validate frame alignment for partial window
                if not self._is_frame_aligned(len(partial_window_data)):
                    await self.services.logging_service.warning(
                        f"Partial window {self._user_chunk_counters[user_id]} for user {user_id} "
                        f"is NOT frame-aligned: {len(partial_window_data)} bytes"
                    )

                await self._flush_user_window(
                    user_id=user_id,
                    chunk_idx=self._user_chunk_counters[user_id],
                    window_data=partial_window_data,
                )

                self._user_chunk_counters[user_id] += 1
                windows_emitted += 1
                total_windows_emitted += 1

            if windows_emitted > 0:
                await self.services.logging_service.info(
                    f"Emitted {windows_emitted} window(s) for user {user_id}"
                )

        if users_with_data > 0:
            await self.services.logging_service.info(
                f"Flushed audio for {users_with_data} user(s), "
                f"total buffer size: {total_buffer_size:,} bytes ({total_buffer_size / 1024 / 1024:.2f} MB), "
                f"total windows emitted: {total_windows_emitted}"
            )
        else:
            await self.services.logging_service.debug(
                f"No audio data to flush in meeting {self.meeting_id}"
            )

    async def _backfill_absent_users(self) -> None:
        """
        Ensure every known user has chunks up to the current global timeline window.
        Emits silent 30s chunks for users whose chunk_idx lags behind the global window count.

        This handles users who have left or are temporarily absent by padding their
        timeline with silence to keep all users aligned to the same global window count.

        Called AFTER each flush cycle to maintain timeline alignment.

        Global timeline: The number of complete 30s windows that have elapsed since
        recording start, calculated as: elapsed_ms // WINDOW_MS
        """
        if not self.start_time:
            return

        current_time = get_current_timestamp_est()
        elapsed_ms = int((current_time - self.start_time).total_seconds() * 1000)
        target_windows = (
            elapsed_ms // DiscordRecorderConstants.WINDOW_MS
        )  # Global timeline window count
        # Note: This is the number of COMPLETE windows, not partial windows

        # Iterate all users we've ever seen (chunk counters map is our source of truth)
        for user_id in list(self._user_chunk_counters.keys()):
            current_idx = self._user_chunk_counters[user_id]

            # If this user is behind the global window count, backfill up to target_windows
            missing = target_windows - current_idx
            if missing > 0:
                await self.services.logging_service.debug(
                    f"Absent-user backfill: user {user_id} needs {missing} window(s) up to {target_windows}"
                )

                while current_idx < target_windows:
                    await self._flush_user_backfill(user_id=user_id, chunk_idx=current_idx)
                    current_idx += 1

                self._user_chunk_counters[user_id] = current_idx

    async def _backfill_to_max_chunks(self) -> None:
        """
        Final equalization: Ensure all users end with the same total chunk count.

        This is the STOP PATH final step that pads stragglers to match the user
        with the most chunks, ensuring perfect alignment for downstream processing.

        Called ONLY during stop_recording after final extract and final flush.

        Timeline guarantee: After this method completes, every user will have
        exactly the same number of chunks, with late joiners and early leavers
        padded with silent 30s windows.

        Stop sequence: extract → flush (force=True) → backfill_to_max_chunks
        This ensures partial windows are emitted before equalization.
        """
        if not self._user_chunk_counters:
            return

        # Find the maximum chunk count across all users
        max_chunks = max(self._user_chunk_counters.values())

        await self.services.logging_service.info(
            f"Final backfill: padding all users to {max_chunks} chunks"
        )

        # Backfill each user to match the max
        for user_id in list(self._user_chunk_counters.keys()):
            current_idx = self._user_chunk_counters[user_id]

            if current_idx < max_chunks:
                missing = max_chunks - current_idx
                await self.services.logging_service.info(
                    f"Final backfill: user {user_id} needs {missing} chunk(s) to reach {max_chunks}"
                )

                while current_idx < max_chunks:
                    await self._flush_user_backfill(user_id=user_id, chunk_idx=current_idx)
                    current_idx += 1

                self._user_chunk_counters[user_id] = current_idx

    async def _flush_user_backfill(self, user_id: int, chunk_idx: int) -> None:
        """
        Flush a single silent 30s window for timeline backfill.

        Used for:
        1. First-packet-anchored backfill (new users joining mid-session)
        2. Absent-user backfill (users who left or are temporarily absent)
        3. Final equalization backfill (stop path padding to max chunks)

        Generates exactly WINDOW_MS (30,000ms) of silence, which equals
        WINDOW_BYTES (5,760,000 bytes) of frame-aligned PCM.

        Args:
            user_id: Discord user ID
            chunk_idx: Window index (0-based, monotonically increasing)
        """
        # Generate exact 30s of silence (frame-aligned)
        window_data = self._silent_gen.generate(DiscordRecorderConstants.WINDOW_MS)

        # Validate the generated silence is exactly WINDOW_BYTES
        if len(window_data) != DiscordRecorderConstants.WINDOW_BYTES:
            await self.services.logging_service.warning(
                f"Backfill silence for user {user_id} chunk {chunk_idx} generated "
                f"{len(window_data)} bytes, expected {DiscordRecorderConstants.WINDOW_BYTES}"
            )

        # Generate unique chunk filename
        pcm_filename = f"{self.meeting_id}_user{user_id}_chunk{chunk_idx:04d}.pcm"
        mp3_filename = f"{self.meeting_id}_user{user_id}_chunk{chunk_idx:04d}.mp3"

        # Write PCM to temp storage
        pcm_path = await self._write_pcm_to_temp(pcm_filename, window_data)

        # Build MP3 output path in temp storage
        temp_storage_path = (
            self.services.recording_file_service_manager.get_temporary_storage_path()
        )
        mp3_path = os.path.join(temp_storage_path, mp3_filename)

        # Create temp recording in SQL with exact timestamp
        # Timestamp = chunk_idx * WINDOW_MS (exact 30s boundaries)
        temp_recording_id = None
        if self.services.sql_recording_service_manager:
            try:
                start_timestamp_ms = chunk_idx * DiscordRecorderConstants.WINDOW_MS

                temp_recording_id = (
                    await self.services.sql_recording_service_manager.insert_temp_recording(
                        user_id=str(user_id),  # Discord user ID
                        meeting_id=self.meeting_id,
                        start_timestamp_ms=start_timestamp_ms,
                        filename=pcm_filename,
                    )
                )

                if temp_recording_id:
                    self._user_temp_recording_ids[user_id].append(temp_recording_id)
            except Exception as e:
                await self.services.logging_service.error(
                    f"CRITICAL DISCORD RECORDER SQL ERROR: Failed to insert backfill temp recording - "
                    f"Meeting: {self.meeting_id}, User: {user_id}, Chunk: {chunk_idx}, "
                    f"Filename: {pcm_filename}, Error Type: {type(e).__name__}, Details: {str(e)}. "
                    f"This likely indicates a missing meeting entry in the meetings table (foreign key constraint)."
                )
                # Don't raise - allow recording to continue even if SQL fails

        # Queue FFmpeg transcode job
        await self._queue_pcm_to_mp3_transcode(pcm_path, mp3_path, temp_recording_id)

        await self.services.logging_service.debug(
            f"Backfilled silent window {chunk_idx} for user {user_id} in meeting {self.meeting_id} "
            f"(PCM: {pcm_filename}, size: {len(window_data):,} bytes, duration: {DiscordRecorderConstants.WINDOW_MS}ms, "
            f"timestamp: {chunk_idx * DiscordRecorderConstants.WINDOW_MS}ms)"
        )

    async def _flush_user_window(self, user_id: int, chunk_idx: int, window_data: bytes) -> None:
        """
        Flush a single audio window (real data) for a user.

        Handles exact 30s windows (5,760,000 bytes) during normal flush cycles,
        and partial windows (< 30s) on final flush (force=True).

        This method handles:
        1. Writing PCM window to temp storage
        2. Creating temp recording in SQL with exact timestamp
        3. Queuing FFmpeg transcode job

        Timestamp calculation: chunk_idx * WINDOW_MS
        This ensures exact 30s boundaries in the timeline.

        Args:
            user_id: Discord user ID
            chunk_idx: Window index (0-based, monotonically increasing)
            window_data: Exact PCM bytes for this window (typically 30s = 5,760,000 bytes,
                        or partial on final flush)
        """
        # Generate unique chunk filename
        pcm_filename = f"{self.meeting_id}_user{user_id}_chunk{chunk_idx:04d}.pcm"
        mp3_filename = f"{self.meeting_id}_user{user_id}_chunk{chunk_idx:04d}.mp3"

        # Write PCM to temp storage
        pcm_path = await self._write_pcm_to_temp(pcm_filename, window_data)

        # Build MP3 output path in temp storage
        temp_storage_path = (
            self.services.recording_file_service_manager.get_temporary_storage_path()
        )
        mp3_path = os.path.join(temp_storage_path, mp3_filename)

        # Create temp recording in SQL with exact timestamp
        # Timestamp = chunk_idx * WINDOW_MS (exact 30s boundaries)
        temp_recording_id = None
        if self.services.sql_recording_service_manager:
            try:
                start_timestamp_ms = chunk_idx * DiscordRecorderConstants.WINDOW_MS

                temp_recording_id = (
                    await self.services.sql_recording_service_manager.insert_temp_recording(
                        user_id=str(user_id),  # Discord user ID
                        meeting_id=self.meeting_id,
                        start_timestamp_ms=start_timestamp_ms,
                        filename=pcm_filename,
                    )
                )

                if temp_recording_id:
                    self._user_temp_recording_ids[user_id].append(temp_recording_id)
            except Exception as e:
                await self.services.logging_service.error(
                    f"CRITICAL DISCORD RECORDER SQL ERROR: Failed to insert temp recording - "
                    f"Meeting: {self.meeting_id}, User: {user_id}, Chunk: {chunk_idx}, "
                    f"Filename: {pcm_filename}, Error Type: {type(e).__name__}, Details: {str(e)}. "
                    f"This likely indicates a missing meeting entry in the meetings table (foreign key constraint)."
                )
                # Don't raise - allow recording to continue even if SQL fails
                # The file was already saved, so we can manually recover later

        # Queue FFmpeg transcode job
        await self._queue_pcm_to_mp3_transcode(pcm_path, mp3_path, temp_recording_id)

        # Calculate duration for logging
        window_duration_ms = calculate_pcm_duration_ms(
            len(window_data),
            sample_rate=DiscordRecorderConstants.DISCORD_SAMPLE_RATE,
            bits_per_sample=DiscordRecorderConstants.DISCORD_BITS_PER_SAMPLE,
            channels=DiscordRecorderConstants.DISCORD_CHANNELS,
        )

        await self.services.logging_service.info(
            f"Flushed window {chunk_idx} for user {user_id} in meeting {self.meeting_id} "
            f"(PCM: {pcm_filename}, size: {len(window_data):,} bytes, duration: {window_duration_ms}ms, "
            f"timestamp: {chunk_idx * DiscordRecorderConstants.WINDOW_MS}ms)"
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

        # Generate a unique job ID for this FFmpeg job
        job_id = generate_16_char_uuid()

        # Define callback to update SQL status
        async def on_transcode_complete(success: bool) -> None:
            if not self.services.sql_recording_service_manager or not temp_recording_id:
                return

            new_status = TranscodeStatus.DONE if success else TranscodeStatus.FAILED
            await self.services.sql_recording_service_manager.update_temp_recording_status(
                temp_recording_id=temp_recording_id, status=new_status
            )

            # Check and update meeting status based on recording state and pending transcodes
            await self.services.sql_recording_service_manager.check_and_update_meeting_status(
                meeting_id=self.meeting_id, is_recording=self.is_recording
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

        # Queue FFmpeg job with job tracking
        await self.services.ffmpeg_service_manager.queue_pcm_to_mp3(
            input_path=pcm_path,
            output_path=mp3_path,
            bitrate=DiscordRecorderConstants.MP3_BITRATE,
            callback=on_transcode_complete,
            job_id=job_id,
            meeting_id=self.meeting_id,
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

    def was_auto_stopped_due_to_empty_call(self) -> bool:
        """
        Check if the session was auto-stopped due to empty call detection.

        Returns:
            True if session ended because call was empty for threshold cycles
        """
        return (
            self._consecutive_empty_flush_cycles
            >= DiscordRecorderConstants.EMPTY_CALL_FLUSH_CYCLES_THRESHOLD
        )

    def was_auto_stopped_due_to_max_duration(self) -> bool:
        """
        Check if the session was auto-stopped due to exceeding maximum duration.

        Returns:
            True if session ended because it exceeded max duration
        """
        return self._has_exceeded_max_duration()

    def get_auto_stop_reason(self) -> str | None:
        """
        Get the reason for auto-stop, if applicable.

        Returns:
            String describing the auto-stop reason, or None if not auto-stopped
        """
        if self.was_auto_stopped_due_to_max_duration():
            duration_hours = self.get_recording_duration_seconds() / 3600
            return f"Maximum duration exceeded ({duration_hours:.2f} hours)"
        elif self.was_auto_stopped_due_to_empty_call():
            return f"Empty call for {self._consecutive_empty_flush_cycles} consecutive cycles"
        return None

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
            "recording_duration": {
                "seconds": self.get_recording_duration_seconds(),
                "hours": self.get_recording_duration_seconds() / 3600,
                "max_duration_seconds": DiscordRecorderConstants.MAX_RECORDING_DURATION_SECONDS,
                "max_duration_hours": DiscordRecorderConstants.MAX_RECORDING_DURATION_SECONDS
                / 3600,
                "will_auto_stop_next_cycle": self._has_exceeded_max_duration(),
            },
            "empty_call_detection": {
                "consecutive_empty_cycles": self._consecutive_empty_flush_cycles,
                "threshold": DiscordRecorderConstants.EMPTY_CALL_FLUSH_CYCLES_THRESHOLD,
                "is_call_empty": self._is_call_empty(),
                "will_auto_stop_next_cycle": (
                    self._consecutive_empty_flush_cycles
                    >= DiscordRecorderConstants.EMPTY_CALL_FLUSH_CYCLES_THRESHOLD - 1
                ),
            },
            "auto_stop_reason": self.get_auto_stop_reason(),
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

    def __init__(self, context: "Context"):
        super().__init__(context)

        self.sessions: dict[int, DiscordSessionHandler] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None

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

        # Start background monitor task for auto-stopping sessions (empty calls and max duration)
        self._monitor_task = asyncio.create_task(self._monitor_sessions())

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

        # Cancel monitor task
        if self._monitor_task:
            self._monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._monitor_task

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
    ) -> DiscordSessionHandler | None:
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
            return None

        # Generate meeting ID if not provided
        if not meeting_id:
            meeting_id = generate_16_char_uuid()

        # Validate required fields for SQL tracking
        if not user_id or not guild_id:
            await self.services.logging_service.error(
                "user_id and guild_id are required for SQL tracking"
            )
            return None

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
                return None

        # Create session handler
        session = DiscordSessionHandler(
            discord_voice_client=discord_voice_client,
            channel_id=channel_id,
            meeting_id=meeting_id,
            user_id=user_id,
            guild_id=guild_id,
            context=self.context,
        )

        # Start recording
        await session.start_recording()

        # Store session
        self.sessions[channel_id] = session

        await self.services.logging_service.info(
            f"Started recording session for meeting {meeting_id}, channel {channel_id}"
        )
        return session

    async def stop_session(self, channel_id: int) -> bool:
        """
        Stop recording audio from a Discord channel and process recordings.

        Steps:
        1. Stop recording session
        2. Wait for pending transcodes to complete
        3. Concatenate MP3 files per user
        4. Create persistent recordings in SQL
        5. Send DM notifications to users
        6. Cleanup session

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
        recorded_user_ids = session.get_recorded_user_ids()

        await self.services.logging_service.info(
            f"Stopping recording session for meeting {meeting_id} with {len(recorded_user_ids)} users"
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

            # Final meeting status check (all transcodes should be done or failed)
            await self.services.sql_recording_service_manager.check_and_update_meeting_status(
                meeting_id=meeting_id, is_recording=False
            )

            # Note: Temp recordings remain in temp storage and SQL
            # They will be cleaned up by the background cleanup task
            await self.services.logging_service.info(
                f"Recording session complete for meeting {meeting_id}. "
                f"Files are in temp storage and will be cleaned up after {DiscordRecorderConstants.TEMP_RECORDING_TTL_HOURS} hours."
            )

        # Cleanup session
        del self.sessions[channel_id]

        # Process recordings in background
        asyncio.create_task(
            self._process_recordings_post_stop(
                meeting_id=meeting_id,
            )
        )

        await self.services.logging_service.info(f"Stopped recording in channel {channel_id}")
        return True

    async def pause_session(self, channel_id: int) -> bool:
        """
        Pause an ongoing recording session and save all recorded data to temp files.

        When paused:
        - Recording stops (flush cycle is cancelled)
        - All accumulated audio is flushed to temp files (saved for later processing)
        - Audio buffers are cleared to free memory
        - Session remains alive and can be resumed with /resume

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

        meeting_id = session.meeting_id

        # Pause the session using the session handler's pause method
        await session.pause_recording()

        # Update meeting status to PAUSED in database
        if self.services.sql_recording_service_manager:
            try:
                await self.services.sql_recording_service_manager.update_meeting_status(
                    meeting_id=meeting_id, status=MeetingStatus.PAUSED
                )
                await self.services.logging_service.info(
                    f"Updated meeting {meeting_id} status to PAUSED"
                )
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to update meeting status to PAUSED for meeting {meeting_id}: {e}"
                )

        await self.services.logging_service.info(
            f"Paused recording session for channel {channel_id} and saved all accumulated data to temp files"
        )
        return True

    async def resume_session(self, channel_id: int) -> bool:
        """
        Resume a paused recording session.

        This will:
        1. Clear the sink's audio data and reset tracking variables
        2. Adjust start_time to account for the pause duration
        3. Restart recording with a fresh timeline
        4. Update database status to RECORDING

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

        meeting_id = session.meeting_id

        # Resume recording using the session handler's resume method
        await session.resume_recording()

        # Update meeting status back to RECORDING in database
        if self.services.sql_recording_service_manager:
            try:
                await self.services.sql_recording_service_manager.update_meeting_status(
                    meeting_id=meeting_id, status=MeetingStatus.RECORDING
                )
                await self.services.logging_service.info(
                    f"Updated meeting {meeting_id} status to RECORDING"
                )
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to update meeting status to RECORDING for meeting {meeting_id}: {e}"
                )

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

    async def _send_recording_notification(
        self,
        user_id: int | str,
        meeting_id: str,
        recording_id: str,
        output_filename: str,
    ) -> bool:
        """
        Send a recording completion notification to a Discord user.

        Args:
            user_id: Discord user ID (int or string)
            meeting_id: Meeting ID
            recording_id: Recording ID
            output_filename: Name of the output file

        Returns:
            True if notification was sent successfully, False otherwise
        """
        if not self.context.bot:
            await self.services.logging_service.warning(
                "Bot instance not available in context, cannot send DM notification"
            )
            return False

        message = (
            f"✅ Your recording from meeting `{meeting_id}` has been processed and saved!\n"
            f"Recording ID: `{recording_id}`\n"
            f"File: `{output_filename}`"
        )

        return await BotUtils.send_dm(self.context.bot, user_id, message)

    async def _process_user_recordings(
        self,
        user_id: int | str,
        recordings: list[dict],
        meeting_id: str,
    ) -> bool:
        """
        Process and concatenate all recordings for a specific user in a meeting.

        Args:
            user_id: Discord user ID
            recordings: List of temp recording dictionaries for this user
            meeting_id: Meeting ID

        Returns:
            True if processing succeeded, False otherwise
        """
        try:
            await self.services.logging_service.info(
                f"Processing {len(recordings)} recordings for user {user_id} in meeting {meeting_id}"
            )

            # Sort recordings by timestamp
            recordings.sort(key=lambda x: x.get("timestamp_ms", 0))

            # Get MP3 file paths (only successfully transcoded files)
            mp3_files = []
            for rec in recordings:
                filename = rec.get("filename")
                if filename:
                    # SQL stores PCM filename, convert to MP3 filename
                    mp3_filename = filename.replace(".pcm", ".mp3")

                    # Construct full path using recording file service
                    temp_path = (
                        self.services.recording_file_service_manager.get_temporary_storage_path()
                    )
                    full_path = os.path.join(temp_path, mp3_filename)

                    # Check if file exists (use executor for async compatibility)
                    loop = asyncio.get_event_loop()
                    exists = await loop.run_in_executor(None, os.path.exists, full_path)

                    if exists:
                        mp3_files.append(full_path)
                    else:
                        await self.services.logging_service.debug(
                            f"MP3 file not found: {mp3_filename}"
                        )

            if not mp3_files:
                await self.services.logging_service.warning(
                    f"No MP3 files found for user {user_id} in meeting {meeting_id}"
                )
                return False

            await self.services.logging_service.info(
                f"Found {len(mp3_files)} MP3 files for user {user_id}"
            )

            # Concatenate MP3 files into one big file
            output_filename = f"{meeting_id}_user{user_id}_final.mp3"
            output_path = await self._concatenate_mp3_files(
                mp3_files, output_filename, meeting_id, user_id
            )

            if not output_path:
                await self.services.logging_service.error(
                    f"Failed to concatenate MP3 files for user {user_id} in meeting {meeting_id}"
                )
                return False

            # Insert persistent recording into SQL (use full path for file operations)
            recording_id = (
                await self.services.sql_recording_service_manager.insert_persistent_recording(
                    user_id=user_id,
                    meeting_id=meeting_id,
                    filename=output_path,  # Use full path for SHA256 and duration calculation
                )
            )

            await self.services.logging_service.info(
                f"Successfully created persistent recording {recording_id} for user {user_id} in meeting {meeting_id}"
            )

            # Log the transcoding completion to jobs_status table
            if self.services.sql_logging_service_manager:
                from source.server.sql_models import JobsStatus, JobsType
                from source.utils import generate_16_char_uuid, get_current_timestamp_est

                try:
                    job_id = generate_16_char_uuid()
                    current_time = get_current_timestamp_est()
                    await self.services.sql_logging_service_manager.log_job_status_event(
                        job_type=JobsType.TRANSCODING,
                        job_id=job_id,
                        meeting_id=meeting_id,
                        created_at=current_time,
                        status=JobsStatus.COMPLETED,
                        started_at=current_time,
                        finished_at=current_time,
                    )
                    await self.services.logging_service.info(
                        f"Logged persistent transcoding completion for user {user_id} in meeting {meeting_id} (job_id: {job_id})"
                    )
                except Exception as e:
                    await self.services.logging_service.error(
                        f"Failed to log persistent transcoding completion to SQL: {str(e)}"
                    )

            # Send DM notification to user if bot instance is available
            await self._send_recording_notification(
                user_id=user_id,
                meeting_id=meeting_id,
                recording_id=recording_id,
                output_filename=output_filename,
            )

            return True

        except Exception as e:
            await self.services.logging_service.error(
                f"Error processing recordings for user {user_id} in meeting {meeting_id}: {e}"
            )
            return False

    async def _process_recordings_post_stop(
        self,
        meeting_id: str,
    ) -> None:
        """
        Process recordings after stopping: concatenate files and create persistent recordings.

        Args:
            meeting_id: Meeting ID for the recording session
        """
        try:
            await self.services.logging_service.info(
                f"Starting post-stop processing for meeting {meeting_id}"
            )

            # Get all temp recordings for this meeting
            temp_recordings = (
                await self.services.sql_recording_service_manager.get_temp_recordings_for_meeting(
                    meeting_id
                )
            )

            if not temp_recordings:
                await self.services.logging_service.warning(
                    f"No temp recordings found for meeting {meeting_id}"
                )
                return

            await self.services.logging_service.info(
                f"Retrieved {len(temp_recordings)} temp recordings for meeting {meeting_id}"
            )

            # Group temp recordings by user
            user_recordings = {}
            for recording in temp_recordings:
                rec_user_id = recording["user_id"]
                if rec_user_id not in user_recordings:
                    user_recordings[rec_user_id] = []
                user_recordings[rec_user_id].append(recording)

            await self.services.logging_service.info(
                f"Grouped recordings by user: {len(user_recordings)} users with recordings"
            )

            # Process each user's recordings
            for rec_user_id, recordings in user_recordings.items():
                await self._process_user_recordings(
                    user_id=rec_user_id,
                    recordings=recordings,
                    meeting_id=meeting_id,
                )

            await self.services.logging_service.info(
                f"Completed post-stop processing for meeting {meeting_id}"
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Error in post-stop processing for meeting {meeting_id}: {e}"
            )

    async def _concatenate_mp3_files(
        self,
        mp3_files: list[str],
        output_filename: str,
        meeting_id: str,
        user_id: int | str,
    ) -> str | None:
        """
        Concatenate multiple MP3 files into one using FFmpeg.

        Args:
            mp3_files: List of MP3 file paths to concatenate
            output_filename: Name for the output file
            meeting_id: Meeting ID for context
            user_id: User ID for context

        Returns:
            Path to the concatenated file, or None if failed
        """
        try:
            if not mp3_files:
                await self.services.logging_service.warning("No MP3 files to concatenate")
                return None

            storage_path = (
                self.services.recording_file_service_manager.get_persistent_storage_path()
            )
            output_path = os.path.join(storage_path, output_filename)

            if len(mp3_files) == 1:
                # Only one file, just copy it to storage
                await self.services.logging_service.debug(
                    f"Single MP3 file, copying to persistent storage: {output_filename}"
                )

                # Copy file
                import shutil

                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, shutil.copy2, mp3_files[0], output_path)

                await self.services.logging_service.info(f"Copied single MP3 file to {output_path}")
                return output_path

            # Concatenate multiple files using FFmpeg
            await self.services.logging_service.info(
                f"Concatenating {len(mp3_files)} MP3 files into {output_filename}"
            )

            # Build FFmpeg command with concat protocol
            # Format: ffmpeg -i "concat:file1.mp3|file2.mp3|file3.mp3" -acodec copy output.mp3
            concat_input = "concat:" + "|".join(mp3_files)

            # Use FFmpeg to concatenate
            success, stdout, stderr = (
                await self.services.ffmpeg_service_manager.handler.convert_file(
                    input_path=concat_input,
                    output_path=output_path,
                    options={
                        "-acodec": "copy",
                        "-y": None,
                    },
                )
            )

            if success:
                await self.services.logging_service.info(
                    f"Successfully concatenated {len(mp3_files)} MP3 files to {output_path}"
                )
                return output_path
            else:
                await self.services.logging_service.error(f"FFmpeg concatenation failed: {stderr}")
                return None

        except Exception as e:
            await self.services.logging_service.error(f"Error concatenating MP3 files: {e}")
            return None

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
    # Background Monitoring Methods
    # -------------------------------------------------------------- #

    async def _monitor_sessions(self) -> None:
        """
        Background task to monitor and auto-stop sessions when:
        1. Calls are empty (no human users)
        2. Recording exceeds maximum duration

        This runs periodically to check if any session's flush loop has detected
        either condition and automatically stops the recording following the /stop logic.
        """
        # Check every 10 seconds for sessions that need auto-stopping
        monitor_interval = 10

        await self.services.logging_service.info(
            f"Started session monitor task (interval: {monitor_interval}s)"
        )

        try:
            while True:
                await asyncio.sleep(monitor_interval)

                # Check all active sessions
                for channel_id in list(self.sessions.keys()):
                    session = self.sessions.get(channel_id)
                    if not session:
                        continue

                    # Check if session should be auto-stopped
                    # The flush loop will break when either threshold is reached, so check if it's still recording
                    should_stop = False
                    stop_reason = None

                    if not session.is_recording:
                        if session.was_auto_stopped_due_to_max_duration():
                            should_stop = True
                            duration_hours = session.get_recording_duration_seconds() / 3600
                            stop_reason = f"maximum duration exceeded ({duration_hours:.2f} hours)"
                        elif session.was_auto_stopped_due_to_empty_call():
                            should_stop = True
                            stop_reason = "empty call detection"

                    if should_stop and stop_reason:
                        await self.services.logging_service.info(
                            f"Auto-stopping session for channel {channel_id} (meeting {session.meeting_id}) "
                            f"due to {stop_reason} - following /stop logic"
                        )

                        # Store voice client reference before stop_session removes the session
                        voice_client = session.discord_voice_client

                        # Execute /stop logic:
                        # 1. Stop recording session (handles transcoding, concatenation, SQL updates, and DMs)
                        await self.stop_session(channel_id=channel_id)

                        # 2. Disconnect from voice channel
                        try:
                            if voice_client and voice_client.is_connected():
                                await voice_client.disconnect()
                                await self.services.logging_service.info(
                                    f"Disconnected bot from channel {channel_id} after auto-stop"
                                )
                        except Exception as e:
                            await self.services.logging_service.error(
                                f"Error disconnecting from voice channel {channel_id}: {e}"
                            )

        except asyncio.CancelledError:
            await self.services.logging_service.info("Session monitor task cancelled")

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

        # Query old temp recordings using SQLAlchemy
        query = select(TempRecordingModel).where(
            TempRecordingModel.created_at < cutoff_time,
            TempRecordingModel.transcode_status.in_(
                [TranscodeStatus.DONE.value, TranscodeStatus.FAILED.value]
            ),
        )

        old_recordings = await self.server.sql_client.execute(query)

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
            # Note: The TempRecordingModel only stores filename, not full paths
            # We need to construct the paths from the filename
            filename = record.get("filename")

            try:
                if filename:
                    temp_path = (
                        self.services.recording_file_service_manager.get_temporary_storage_path()
                    )

                    # Construct PCM and MP3 paths
                    pcm_filename = filename
                    mp3_filename = filename.replace(".pcm", ".mp3")
                    pcm_path = os.path.join(temp_path, pcm_filename)
                    mp3_path = os.path.join(temp_path, mp3_filename)

                    loop = asyncio.get_event_loop()

                    # Delete MP3 file if exists (non-blocking)
                    if os.path.exists(mp3_path):
                        await loop.run_in_executor(None, os.remove, mp3_path)

                    # Delete PCM file if exists (non-blocking)
                    if os.path.exists(pcm_path):
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
