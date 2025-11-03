import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from source.utils import generate_16_char_uuid
from source.server.server import ServerManager
from source.server.sql_models import TranscodeStatus
from source.services.manager import BaseDiscordRecorderServiceManager, ServicesManager


# -------------------------------------------------------------- #
# Configuration Constants
# -------------------------------------------------------------- #


class DiscordRecorderConstants:
    """Configuration constants for Discord recording."""

    # Flush cycle
    FLUSH_INTERVAL_SECONDS = 10  # Configurable: flush buffer every N seconds

    # FFmpeg encoding
    MP3_BITRATE = "128k"  # 128 kbps


# -------------------------------------------------------------- #
# Discord Recorder Service Manager
# -------------------------------------------------------------- #


class DiscordSessionHandler:
    """
    Handler for managing individual Discord recording sessions.

    This class handles:
    - Audio buffering and periodic flushing
    - Temp recording creation in SQL
    - FFmpeg job queuing
    - Session lifecycle management
    """

    def __init__(self):
        pass

    # -------------------------------------------------------------- #
    # Session Lifecycle Methods
    # -------------------------------------------------------------- #

    async def start_recording(self) -> None:
        """Start the recording session and flush cycle."""
        if self.is_recording:
            await self.services.logging_service.warning(
                f"Session {self.channel_id} already recording"
            )
            return

        self.is_recording = True
        self._chunk_counter = 0
        self._temp_recording_ids = []

        await self.services.logging_service.info(
            f"Started recording session for meeting {self.meeting_id}, "
            f"user {self.user_id}, channel {self.channel_id}"
        )

        # Start periodic flush task (every 10 seconds)
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop_recording(self) -> None:
        """Stop the recording session and flush any remaining data."""
        if not self.is_recording:
            return

        # Prevent race conditions - no new audio data during shutdown
        self._is_shutting_down = True
        self.is_recording = False

        # Cancel flush task
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush of any remaining data
        if len(self._audio_buffer) > 0:
            await self._flush_once()

        await self.services.logging_service.info(
            f"Stopped recording session for meeting {self.meeting_id}. "
            f"Created {len(self._temp_recording_ids)} temp recording chunks."
        )

    # -------------------------------------------------------------- #
    # Audio Buffering Methods
    # -------------------------------------------------------------- #

    async def push_audio_data(self, pcm_data: bytes) -> None:
        """
        Push PCM audio data to the buffer.

        Args:
            pcm_data: Raw PCM audio bytes (s16le format)
        """
        # Prevent race conditions during shutdown
        if not self.is_recording or self._is_shutting_down:
            return

        self._audio_buffer.extend(pcm_data)

    # -------------------------------------------------------------- #
    # Flush Cycle (Core Integration Point)
    # -------------------------------------------------------------- #

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
        pass

    # -------------------------------------------------------------- #
    # FFmpeg Integration
    # -------------------------------------------------------------- #

    async def _queue_pcm_to_mp3_transcode(
        self, pcm_path: str, mp3_path: str, temp_recording_id: Optional[str]
    ) -> None:
        """
        Queue a PCM → MP3 transcode job with temp recording tracking.

        Args:
            pcm_path: Path to PCM file
            mp3_path: Path to output MP3 file
            temp_recording_id: Optional temp recording ID for SQL tracking
        """
        pass

    # -------------------------------------------------------------- #
    # Session Information Methods
    # -------------------------------------------------------------- #

    def get_temp_recording_ids(self) -> list[str]:
        """Get all temp recording IDs created during this session."""
        return self._temp_recording_ids.copy()

    async def get_session_status(self) -> dict:
        """Get current session status including SQL tracking info."""
        # Check if SQL recording service is available
        if not self.services.sql_recording_service:
            return {
                "is_recording": self.is_recording,
                "meeting_id": self.meeting_id,
                "user_id": self.user_id,
                "guild_id": self.guild_id,
                "channel_id": self.channel_id,
                "total_chunks": len(self._temp_recording_ids),
                "buffer_size_bytes": len(self._audio_buffer),
                "chunk_statuses": {"note": "SQL service not available"},
            }

        # Query SQL for chunk statuses
        chunks = await self.services.sql_recording_service.get_temp_recordings_for_meeting(
            self.meeting_id
        )

        # Filter to this session's chunks
        session_chunks = [c for c in chunks if c["id"] in self._temp_recording_ids]

        # Count by status (optimized with Counter)
        status_counter = Counter(c["transcode_status"] for c in session_chunks)
        status_counts = {
            "queued": status_counter.get(TranscodeStatus.QUEUED.value, 0),
            "in_progress": status_counter.get(TranscodeStatus.IN_PROGRESS.value, 0),
            "done": status_counter.get(TranscodeStatus.DONE.value, 0),
            "failed": status_counter.get(TranscodeStatus.FAILED.value, 0),
        }

        return {
            "is_recording": self.is_recording,
            "meeting_id": self.meeting_id,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "total_chunks": len(self._temp_recording_ids),
            "buffer_size_bytes": len(self._audio_buffer),
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
        self._cleanup_task: Optional[asyncio.Task] = None

    # -------------------------------------------------------------- #
    # Discord Recorder Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services_manager: "ServicesManager") -> None:
        """Initialize the Discord Recorder Service Manager."""
        await super().on_start(services_manager)
        await self.services.logging_service.info("Discord Recorder Service Manager started")

        # Start background cleanup task for old temp recordings
        if self.services.sql_recording_service:
            self._cleanup_task = asyncio.create_task(self._cleanup_old_temp_recordings())

    async def on_close(self) -> bool:
        """Stop the Discord Recorder Service Manager."""
        # Stop all active sessions
        for channel_id in list(self.sessions.keys()):
            await self.stop_session(channel_id)

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        await self.services.logging_service.info("Discord Recorder Service Manager stopped")
        return True

    # -------------------------------------------------------------- #
    # Session Management Methods
    # -------------------------------------------------------------- #

    async def start_session(
        self,
        channel_id: int,
        meeting_id: Optional[str] = None,
        user_id: Optional[str] = None,
        guild_id: Optional[str] = None,
    ) -> bool:
        """
        Start recording audio from a Discord channel.

        Args:
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

        # Create session handler
        session = DiscordSessionHandler(
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
        if self.services.sql_recording_service:
            await self.services.logging_service.info(
                f"Waiting for pending transcodes for meeting {meeting_id}..."
            )

            completed = await self._wait_for_pending_transcodes(
                meeting_id=meeting_id,
                max_wait_seconds=RecordingConfig.TRANSCODE_TIMEOUT_SECONDS,
            )

            if not completed:
                await self.services.logging_service.warning(
                    f"Timeout waiting for transcodes on meeting {meeting_id}"
                )

            # Promote temp recordings to persistent storage
            await self.services.logging_service.info(
                f"Promoting temp recordings for meeting {meeting_id}..."
            )

            recording_id = (
                await self.services.sql_recording_service.promote_temp_recordings_to_persistent(
                    meeting_id=meeting_id,
                    user_id=user_id,
                )
            )

            if recording_id:
                await self.services.logging_service.info(
                    f"Successfully promoted temp recordings to persistent recording: {recording_id}"
                )
            else:
                await self.services.logging_service.warning(
                    f"No temp recordings to promote for meeting {meeting_id}"
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
            try:
                await session._flush_task
            except asyncio.CancelledError:
                pass

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
    # Promotion Helper Methods
    # -------------------------------------------------------------- #

    async def _wait_for_pending_transcodes(
        self,
        meeting_id: str,
        max_wait_seconds: int = RecordingConfig.TRANSCODE_TIMEOUT_SECONDS,
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
            chunks = await self.services.sql_recording_service.get_temp_recordings_for_meeting(
                meeting_id
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
        cleanup_interval = RecordingConfig.CLEANUP_INTERVAL_SECONDS
        ttl_hours = RecordingConfig.TEMP_RECORDING_TTL_HOURS

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
        query = f"""
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
                # Delete MP3 file if exists
                if mp3_path and os.path.exists(mp3_path):
                    os.remove(mp3_path)

                # Delete PCM file if exists (should already be deleted, but check)
                if pcm_path and os.path.exists(pcm_path):
                    os.remove(pcm_path)

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
        batch_size = RecordingConfig.MAX_DELETE_BATCH_SIZE

        for i in range(0, len(temp_ids), batch_size):
            batch = temp_ids[i : i + batch_size]
            try:
                await self.services.sql_recording_service.delete_temp_recordings(batch)
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to delete batch of {len(batch)} temp recordings: {e}"
                )

    # -------------------------------------------------------------- #
    # Session Information Methods
    # -------------------------------------------------------------- #

    async def get_session_status(self, channel_id: int) -> Optional[dict]:
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
