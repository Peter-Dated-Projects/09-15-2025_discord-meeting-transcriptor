from datetime import datetime
from typing import Optional

from source.server.server import ServerManager
from source.server.sql_models import (
    RecordingModel,
    TempRecordingModel,
    TranscodeStatus,
)
from source.services.manager import Manager
from source.utils import (
    DISCORD_GUILD_ID_MIN_LENGTH,
    DISCORD_USER_ID_MIN_LENGTH,
    generate_16_char_uuid,
    get_current_timestamp_est,
)

# -------------------------------------------------------------- #
# SQL Recording Manager Service
# -------------------------------------------------------------- #


class SQLRecordingManagerService(Manager):
    """Service for managing SQL recording operations (temp and persistent)."""

    def __init__(self, server: ServerManager):
        super().__init__(server)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("SQLRecordingManagerService initialized")
        return True

    async def on_close(self):
        await self.services.logging_service.info("SQLRecordingManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Temp Recording CRUD Methods
    # -------------------------------------------------------------- #

    async def insert_temp_recording(
        self, user_id: str, meeting_id: str, start_timestamp_ms: int
    ) -> str:
        """
        Insert a new temp recording chunk when PCM file is flushed.

        Args:
            user_id: Discord User ID of the participant
            meeting_id: Meeting ID (16 chars)

        Returns:
            temp_recording_id: The generated ID for the temp recording
        """

        # Validate inputs
        if len(user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )
        if len(meeting_id) < DISCORD_GUILD_ID_MIN_LENGTH:
            raise ValueError(
                f"meeting_id must be at least {DISCORD_GUILD_ID_MIN_LENGTH} characters long"
            )

        # entry data
        entry_id = generate_16_char_uuid()
        timestamp = get_current_timestamp_est()
        filename = (
            f"{timestamp.strftime('%Y-%m-%d')}_recording_{user_id}_{int(start_timestamp_ms)}.pcm"
        )

        temp_recording = TempRecordingModel(
            id=entry_id,
            user_id=user_id,
            meeting_id=meeting_id,
            created_at=timestamp,
            filename=filename,
        )

        # Convert to dict for insertion
        temp_data = {
            "id": temp_recording.id,
            "user_id": temp_recording.user_id,
            "meeting_id": temp_recording.meeting_id,
            "created_at": temp_recording.created_at,
            "filename": temp_recording.filename,
        }

        # Insert data to sql table
        await self.server.sql_client.insert(TempRecordingModel.__tablename__, temp_data)
        await self.services.logging_service.info(
            f"Inserted temp recording: {entry_id} for meeting {meeting_id}"
        )

        return entry_id

    async def update_temp_recording_transcode_started(self, temp_recording_id: str) -> None:
        """
        Update temp recording when FFmpeg transcode job starts.

        Args:
            temp_recording_id: Temp recording ID to update
        """
        if len(temp_recording_id) != 16:
            raise ValueError("temp_recording_id must be 16 characters long")

        update_data = {
            "transcode_status": TranscodeStatus.IN_PROGRESS.value,
        }
        conditions = {"id": temp_recording_id}

        await self.server.sql_client.update(
            TempRecordingModel.__tablename__, update_data, conditions
        )
        await self.services.logging_service.info(
            f"Updated temp recording {temp_recording_id}: transcode started"
        )

    async def update_temp_recording_transcode_completed(
        self,
        temp_recording_id: str,
        mp3_path: str,
        sha256: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """
        Update temp recording when FFmpeg transcode job completes successfully.

        Args:
            temp_recording_id: Temp recording ID to update
            mp3_path: Path to the generated MP3 file
            sha256: Optional SHA256 hash of the MP3 file
            duration_ms: Optional duration in milliseconds
        """
        if len(temp_recording_id) != 16:
            raise ValueError("temp_recording_id must be 16 characters long")

        update_data = {
            "mp3_path": mp3_path,
            "transcode_status": TranscodeStatus.DONE.value,
            "completed_at": datetime.utcnow(),
            "sha256": sha256,
            "duration_ms": duration_ms,
        }
        conditions = {"id": temp_recording_id}

        await self.server.sql_client.update(
            TempRecordingModel.__tablename__, update_data, conditions
        )
        await self.services.logging_service.info(
            f"Updated temp recording {temp_recording_id}: transcode completed"
        )

    async def update_temp_recording_transcode_failed(self, temp_recording_id: str) -> None:
        """
        Update temp recording when FFmpeg transcode job fails.

        Args:
            temp_recording_id: Temp recording ID to update
        """
        if len(temp_recording_id) != 16:
            raise ValueError("temp_recording_id must be 16 characters long")

        update_data = {
            "transcode_status": TranscodeStatus.FAILED.value,
            "completed_at": datetime.utcnow(),
        }
        conditions = {"id": temp_recording_id}

        await self.server.sql_client.update(
            TempRecordingModel.__tablename__, update_data, conditions
        )
        await self.services.logging_service.error(
            f"Updated temp recording {temp_recording_id}: transcode failed"
        )

    async def mark_temp_recording_cleaned(self, temp_recording_id: str) -> None:
        """
        Mark temp recording as cleaned (PCM file deleted).

        Args:
            temp_recording_id: Temp recording ID to update
        """
        if len(temp_recording_id) != 16:
            raise ValueError("temp_recording_id must be 16 characters long")

        update_data = {"cleaned": 1}
        conditions = {"id": temp_recording_id}

        await self.server.sql_client.update(
            TempRecordingModel.__tablename__, update_data, conditions
        )
        await self.services.logging_service.info(
            f"Marked temp recording {temp_recording_id} as cleaned"
        )

    async def get_temp_recordings_for_meeting(
        self, meeting_id: str, status_filter: Optional[TranscodeStatus] = None
    ) -> list[dict]:
        """
        Get all temp recordings for a meeting, optionally filtered by status.

        Args:
            meeting_id: Meeting ID
            status_filter: Optional TranscodeStatus to filter by

        Returns:
            List of temp recording dictionaries
        """
        if len(meeting_id) != 16:
            raise ValueError("meeting_id must be 16 characters long")

        if status_filter:
            query = f"""
                SELECT * FROM {TempRecordingModel.__tablename__}
                WHERE meeting_id = :meeting_id AND transcode_status = :status
                ORDER BY created_at ASC
            """
            params = {"meeting_id": meeting_id, "status": status_filter.value}
        else:
            query = f"""
                SELECT * FROM {TempRecordingModel.__tablename__}
                WHERE meeting_id = :meeting_id
                ORDER BY created_at ASC
            """
            params = {"meeting_id": meeting_id}

        results = await self.server.sql_client.query(query, params)
        return results

    async def delete_temp_recordings(self, temp_recording_ids: list[str]) -> None:
        """
        Delete temp recording records (e.g., after promotion to persistent).

        Args:
            temp_recording_ids: List of temp recording IDs to delete
        """
        if not temp_recording_ids:
            return

        # Validate all IDs
        for tid in temp_recording_ids:
            if len(tid) != 16:
                raise ValueError(f"Invalid temp_recording_id: {tid} must be 16 characters")

        # Build delete query
        placeholders = ", ".join([f":id_{i}" for i in range(len(temp_recording_ids))])
        query = f"""
            DELETE FROM {TempRecordingModel.__tablename__}
            WHERE id IN ({placeholders})
        """
        params = {f"id_{i}": tid for i, tid in enumerate(temp_recording_ids)}

        await self.server.sql_client.query(query, params)
        await self.services.logging_service.info(
            f"Deleted {len(temp_recording_ids)} temp recording(s)"
        )

    # -------------------------------------------------------------- #
    # Persistent Recording CRUD Methods
    # -------------------------------------------------------------- #

    async def insert_persistent_recording(
        self,
        meeting_id: str,
        filename: str,
        duration_ms: int,
        sha256: str,
        created_at: Optional[datetime] = None,
    ) -> str:
        """
        Insert a persistent recording after promoting from temp chunks.

        Args:
            meeting_id: Meeting ID
            filename: Recording filename
            duration_ms: Total duration in milliseconds
            sha256: SHA256 hash of the recording
            created_at: Optional timestamp (defaults to now)

        Returns:
            recording_id: The generated ID for the persistent recording
        """
        recording_id = generate_16_char_uuid()
        timestamp = created_at or datetime.utcnow()

        if len(meeting_id) != 16:
            raise ValueError("meeting_id must be 16 characters long")

        recording = RecordingModel(
            id=recording_id,
            created_at=timestamp,
            duration_in_ms=duration_ms,
            meeting_id=meeting_id,
            sha256=sha256,
            filename=filename,
        )

        recording_data = {
            "id": recording.id,
            "created_at": recording.created_at,
            "duration_in_ms": recording.duration_in_ms,
            "meeting_id": recording.meeting_id,
            "sha256": recording.sha256,
            "filename": recording.filename,
        }

        await self.server.sql_client.insert(RecordingModel.__tablename__, recording_data)
        await self.services.logging_service.info(
            f"Inserted persistent recording: {recording_id} for meeting {meeting_id}"
        )

        return recording_id

    # -------------------------------------------------------------- #
    # Promotion Flow Methods
    # -------------------------------------------------------------- #

    async def promote_temp_recordings_to_persistent(
        self,
        meeting_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Promote all completed temp recordings for a meeting/user to persistent storage.

        This aggregates all DONE temp chunks, computes total duration,
        and creates a single persistent recording entry.

        Args:
            meeting_id: Meeting ID
            user_id: Optional user ID to filter temp recordings

        Returns:
            recording_id: The ID of the created persistent recording, or None if no chunks
        """
        # Get all completed temp recordings for the meeting
        temp_chunks = await self.get_temp_recordings_for_meeting(
            meeting_id, status_filter=TranscodeStatus.DONE
        )

        # Filter by user if specified
        if user_id:
            temp_chunks = [chunk for chunk in temp_chunks if chunk.get("user_id") == user_id]

        if not temp_chunks:
            await self.services.logging_service.warning(
                f"No completed temp recordings found for meeting {meeting_id}"
            )
            return None

        # Compute aggregated values
        total_duration_ms = sum(chunk.get("duration_ms", 0) for chunk in temp_chunks)

        # For filename, you might want to construct it based on meeting/user
        # For now, using the first chunk's mp3_path as a reference
        first_chunk = temp_chunks[0]
        base_filename = f"recording_{meeting_id}"
        if user_id:
            base_filename += f"_{user_id}"
        base_filename += ".mp3"

        # Create a combined SHA256 (or use the first chunk's, depending on your merge strategy)
        # Here we'll use a placeholder - you'd implement your actual merge logic
        combined_sha256 = first_chunk.get("sha256", "")

        # Insert persistent recording
        recording_id = await self.insert_persistent_recording(
            meeting_id=meeting_id,
            filename=base_filename,
            duration_ms=total_duration_ms,
            sha256=combined_sha256,
        )

        # Optionally delete temp recordings after promotion
        temp_ids = [chunk["id"] for chunk in temp_chunks]
        await self.delete_temp_recordings(temp_ids)

        await self.services.logging_service.info(
            f"Promoted {len(temp_chunks)} temp recording(s) to persistent recording {recording_id}"
        )

        return recording_id
