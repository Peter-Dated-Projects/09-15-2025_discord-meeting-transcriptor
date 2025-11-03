from sqlalchemy import delete, insert, select

from source.server.server import ServerManager
from source.server.sql_models import (
    RecordingModel,
    TempRecordingModel,
)
from source.services.manager import Manager
from source.utils import (
    DISCORD_USER_ID_MIN_LENGTH,
    MEETING_UUID_LENGTH,
    calculate_audio_file_duration_ms,
    calculate_file_sha256,
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
        self, user_id: str, meeting_id: str, start_timestamp_ms: int, filename: str
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
        if len(meeting_id) < MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be at least {MEETING_UUID_LENGTH} characters long")

        # entry data
        entry_id = generate_16_char_uuid()
        timestamp = get_current_timestamp_est()

        temp_recording = TempRecordingModel(
            id=entry_id,
            user_id=user_id,
            meeting_id=meeting_id,
            created_at=timestamp,
            filename=filename,
            timestamp_ms=start_timestamp_ms,
        )

        # Convert to dict for insertion
        temp_data = {
            "id": temp_recording.id,
            "user_id": temp_recording.user_id,
            "meeting_id": temp_recording.meeting_id,
            "created_at": temp_recording.created_at,
            "filename": temp_recording.filename,
            "timestamp_ms": temp_recording.timestamp_ms,
        }

        # Build and execute insert statement
        stmt = insert(TempRecordingModel).values(**temp_data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Inserted temp recording: {entry_id} for meeting {meeting_id}"
        )

        return entry_id

    async def delete_temp_recording(self, temp_recording_entry_id: str) -> None:
        """
        Delete a temp recording entry by its ID.

        Args:
            temp_recording_entry_id: The ID of the temp recording to delete
        """

        # Validate input
        if len(temp_recording_entry_id) != 16:
            raise ValueError("temp_recording_entry_id must be 16 characters long")

        # Build delete query
        query = delete(TempRecordingModel).where(TempRecordingModel.id == temp_recording_entry_id)

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted temp recording: {temp_recording_entry_id}"
        )

    async def delete_temp_recordings(self, temp_recording_entry_ids: list[str]) -> None:
        """
        Delete multiple temp recording entries by their IDs.

        Args:
            temp_recording_entry_ids: List of temp recording IDs to delete
        """

        # Validate input
        for entry_id in temp_recording_entry_ids:
            if len(entry_id) != 16:
                raise ValueError("All temp_recording_entry_ids must be 16 characters long")

        # Build delete query
        query = delete(TempRecordingModel).where(
            TempRecordingModel.id.in_(temp_recording_entry_ids)
        )

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted {len(temp_recording_entry_ids)} temp recordings"
        )

    # -------------------------------------------------------------- #
    # Persistent Recording CRUD Methods
    # -------------------------------------------------------------- #

    async def insert_persistent_recording(
        self,
        user_id: str,
        meeting_id: str,
        filename: str,
    ) -> str:
        """
        Insert a new persistent recording chunk when PCM file is flushed.

        Args:
            user_id: Discord User ID of the participant
            meeting_id: Meeting ID (16 chars)
            start_timestamp_ms: Start timestamp in milliseconds
            filename: Path to the recording file
            duration_in_ms: Duration of the recording in milliseconds (default: 0)

        Returns:
            recording_id: The generated ID for the persistent recording
        """

        # Validate inputs
        if len(user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )
        if len(meeting_id) < MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be at least {MEETING_UUID_LENGTH} characters long")

        # entry data
        entry_id = generate_16_char_uuid()
        timestamp = get_current_timestamp_est()
        sha256 = calculate_file_sha256(filename)
        file_duration_ms = calculate_audio_file_duration_ms(filename)

        recording = RecordingModel(
            id=entry_id,
            user_id=user_id,
            meeting_id=meeting_id,
            created_at=timestamp,
            duration_in_ms=file_duration_ms,
            filename=filename,
            sha256=sha256,
        )

        # Convert to dict for insertion
        data = {
            "id": recording.id,
            "user_id": recording.user_id,
            "meeting_id": recording.meeting_id,
            "created_at": recording.created_at,
            "duration_in_ms": recording.duration_in_ms,
            "filename": recording.filename,
            "sha256": recording.sha256,
        }

        # Build and execute insert statement
        stmt = insert(RecordingModel).values(**data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Inserted recording: {entry_id} for meeting {meeting_id}"
        )

        return entry_id

    async def delete_persistent_recording(self, recording_entry_id: str) -> None:
        """
        Delete a persistent recording entry by its ID.

        Args:
            recording_entry_id: The ID of the persistent recording to delete
        """

        # Validate input
        if len(recording_entry_id) != 16:
            raise ValueError("recording_entry_id must be 16 characters long")

        # Build delete query
        query = delete(RecordingModel).where(RecordingModel.id == recording_entry_id)

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted persistent recording: {recording_entry_id}"
        )

    async def delete_persistent_recordings(self, recording_entry_ids: list[str]) -> None:
        """
        Delete multiple persistent recording entries by their IDs.

        Args:
            recording_entry_ids: List of persistent recording IDs to delete
        """

        # Validate input
        for entry_id in recording_entry_ids:
            if len(entry_id) != 16:
                raise ValueError("All recording_entry_ids must be 16 characters long")

        # Build delete query
        query = delete(RecordingModel).where(RecordingModel.id.in_(recording_entry_ids))

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted {len(recording_entry_ids)} persistent recordings"
        )

    # -------------------------------------------------------------- #
    # Meeting Methods
    # -------------------------------------------------------------- #

    async def get_temp_recordings_for_meeting(self, meeting_id: str) -> list[dict]:
        """
        Get all temp recordings for a meeting, optionally filtered by status.

        Args:
            meeting_id: Meeting ID
            status_filter: Optional TranscodeStatus to filter by

        Returns:
            List of temp recording dictionaries
        """

        # Validate inputs
        if len(meeting_id) != 16:
            raise ValueError("meeting_id must be 16 characters long")

        # Build and execute query
        query = select(TempRecordingModel).where(TempRecordingModel.meeting_id == meeting_id)
        results = await self.server.sql_client.execute(query)

        return results

    async def get_persistent_recordings_for_meeting(self, meeting_id: str) -> list[dict]:
        """
        Get all persistent recordings for a meeting.

        Args:
            meeting_id: Meeting ID
        Returns:
            List of persistent recording dictionaries
        """

        # Validate inputs
        if len(meeting_id) != 16:
            raise ValueError("meeting_id must be 16 characters long")

        # Build and execute query
        query = select(RecordingModel).where(RecordingModel.meeting_id == meeting_id)
        results = await self.server.sql_client.execute(query)

        return results

    # -------------------------------------------------------------- #
    # User Methods
    # -------------------------------------------------------------- #

    async def get_temp_recordings_for_user(self, user_id: str) -> list[dict]:
        """
        Get all temp recordings for a user.

        Args:
            user_id: Discord User ID of the participant
        Returns:
            List of temp recording dictionaries
        """

        # Validate inputs
        if len(user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        # Build and execute query
        query = select(TempRecordingModel).where(TempRecordingModel.user_id == user_id)
        results = await self.server.sql_client.execute(query)

        return results

    async def get_persistent_recordings_for_user(self, user_id: str) -> list[dict]:
        """
        Get all persistent recordings for a user.

        Args:
            user_id: Discord User ID of the participant
        Returns:
            List of persistent recording dictionaries
        """

        # Validate inputs
        if len(user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        # Build and execute query
        query = select(RecordingModel).where(RecordingModel.user_id == user_id)
        results = await self.server.sql_client.execute(query)

        return results

    # -------------------------------------------------------------- #
    # User + Meeting Specific Methods
    # -------------------------------------------------------------- #

    async def get_temp_recordings_for_user_in_meeting(
        self, user_id: str, meeting_id: str
    ) -> list[dict]:
        """
        Get all temp recordings for a user in a specific meeting.

        Args:
            user_id: Discord User ID of the participant
            meeting_id: Meeting ID
        Returns:
            List of temp recording dictionaries
        """

        # Validate inputs
        if len(user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        # Build and execute query
        query = select(TempRecordingModel).where(
            (TempRecordingModel.user_id == user_id) & (TempRecordingModel.meeting_id == meeting_id)
        )
        results = await self.server.sql_client.execute(query)

        return results

    async def get_persistent_recordings_for_user_in_meeting(
        self, user_id: str, meeting_id: str
    ) -> list[dict]:
        """
        Get all persistent recordings for a user in a specific meeting.

        Args:
            user_id: Discord User ID of the participant
            meeting_id: Meeting ID
        Returns:
            List of persistent recording dictionaries
        """

        # Validate inputs
        if len(user_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"user_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        # Build and execute query
        query = select(RecordingModel).where(
            (RecordingModel.user_id == user_id) & (RecordingModel.meeting_id == meeting_id)
        )
        results = await self.server.sql_client.execute(query)

        return results
