from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select, update

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import (
    JobsStatus,
    JobsStatusModel,
    JobsType,
    MeetingModel,
    MeetingStatus,
    RecordingModel,
    TempRecordingModel,
    TranscodeStatus,
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

    def __init__(self, context: "Context"):
        super().__init__(context)

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
            transcode_status=TranscodeStatus.QUEUED.value,
        )

        # Convert to dict for insertion
        temp_data = {
            "id": temp_recording.id,
            "user_id": temp_recording.user_id,
            "meeting_id": temp_recording.meeting_id,
            "created_at": temp_recording.created_at,
            "filename": temp_recording.filename,
            "timestamp_ms": temp_recording.timestamp_ms,
            "transcode_status": temp_recording.transcode_status,
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

    async def update_temp_recording_status(
        self, temp_recording_id: str, status: TranscodeStatus
    ) -> None:
        """
        Update the transcode status of a temp recording.

        Args:
            temp_recording_id: The ID of the temp recording to update
            status: New TranscodeStatus value
        """
        # Validate input
        if len(temp_recording_id) != 16:
            raise ValueError("temp_recording_id must be 16 characters long")

        # Build update query
        stmt = (
            update(TempRecordingModel)
            .where(TempRecordingModel.id == temp_recording_id)
            .values(transcode_status=status.value)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.debug(
            f"Updated temp recording {temp_recording_id} status to {status.value}"
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
            filename: Path to the recording file (can be full path or just filename)

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

        # Calculate SHA256 and duration from the file (needs full path)
        sha256 = await calculate_file_sha256(filename)
        file_duration_ms = calculate_audio_file_duration_ms(filename)

        # Extract just the filename (not full path) for database storage
        import os

        filename_only = os.path.basename(filename)

        recording = RecordingModel(
            id=entry_id,
            user_id=user_id,
            meeting_id=meeting_id,
            created_at=timestamp,
            duration_in_ms=file_duration_ms,
            filename=filename_only,  # Store only the filename, not full path
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

    async def get_meeting(self, meeting_id: str) -> dict:
        """
        Get meeting details by meeting ID.

        Args:
            meeting_id: Meeting ID (16 chars)

        Returns:
            Meeting details as a dictionary
        """

        # Validate input
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        # Build and execute query
        query = select(MeetingModel).where(MeetingModel.id == meeting_id)
        results = await self.server.sql_client.execute(query)

        if results:
            return results[0]
        else:
            raise ValueError(f"Meeting with ID {meeting_id} not found")

    async def insert_meeting(
        self,
        meeting_id: str,
        guild_id: str,
        channel_id: str,
        requested_by: str,
    ) -> str:
        """
        Insert a new meeting entry when recording starts.

        Args:
            meeting_id: Meeting ID (16 chars)
            guild_id: Discord Guild ID
            channel_id: Discord Channel ID
            requested_by: Discord User ID of the user who requested the recording

        Returns:
            meeting_id: The meeting ID (same as input, for consistency with other insert methods)
        """
        # Validate inputs
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")
        if len(guild_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"guild_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )
        if len(channel_id) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"channel_id must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )
        if len(requested_by) < DISCORD_USER_ID_MIN_LENGTH:
            raise ValueError(
                f"requested_by must be at least {DISCORD_USER_ID_MIN_LENGTH} characters long"
            )

        timestamp = get_current_timestamp_est()

        meeting = MeetingModel(
            id=meeting_id,
            guild_id=guild_id,
            channel_id=channel_id,
            started_at=timestamp,
            ended_at=timestamp,  # Will be updated when recording stops
            updated_at=timestamp,
            status=MeetingStatus.RECORDING.value,
            requested_by=requested_by,
            participants={},  # Will be populated when recording stops with users who spoke
            recording_files={},  # Will be populated as recordings are created
            transcript_ids={},  # Will be populated when transcripts are generated
        )

        # Convert to dict for insertion
        meeting_data = {
            "id": meeting.id,
            "guild_id": meeting.guild_id,
            "channel_id": meeting.channel_id,
            "started_at": meeting.started_at,
            "ended_at": meeting.ended_at,
            "updated_at": meeting.updated_at,
            "status": meeting.status,
            "requested_by": meeting.requested_by,
            "participants": meeting.participants,
            "recording_files": meeting.recording_files,
            "transcript_ids": meeting.transcript_ids,
        }

        # Build and execute insert statement
        stmt = insert(MeetingModel).values(**meeting_data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Inserted meeting: {meeting_id} in guild {guild_id}, channel {channel_id}"
        )

        return meeting_id

    async def update_meeting_status(self, meeting_id: str, status: MeetingStatus) -> None:
        """
        Update the status of a meeting.

        Args:
            meeting_id: Meeting ID (16 chars)
            status: New MeetingStatus value
        """
        # Validate input
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        timestamp = get_current_timestamp_est()

        # Build update query
        stmt = (
            update(MeetingModel)
            .where(MeetingModel.id == meeting_id)
            .values(status=status.value, updated_at=timestamp)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Updated meeting {meeting_id} status to {status.value}"
        )

    async def update_meeting_participants(
        self, meeting_id: str, participant_user_ids: list[int | str]
    ) -> None:
        """
        Update the participants list for a meeting.

        Args:
            meeting_id: Meeting ID (16 chars)
            participant_user_ids: List of Discord User IDs who spoke during the meeting
        """
        # Validate input
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        # Convert all user IDs to strings for consistency
        participants_list = {"users": [str(user_id) for user_id in participant_user_ids]}

        timestamp = get_current_timestamp_est()

        # Build update query
        stmt = (
            update(MeetingModel)
            .where(MeetingModel.id == meeting_id)
            .values(participants=participants_list, updated_at=timestamp)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Updated meeting {meeting_id} with {len(participants_list)} participants: {participants_list}"
        )

    async def update_meeting_transcript_ids(
        self,
        meeting_id: str,
        user_transcript_mapping: dict[str, str],
        meeting_summary_path: str | None = None,
    ) -> None:
        """
        Update the transcript_ids field for a meeting with the new format.

        New format:
        {
            "meeting_summary": "{meeting_summary_file_path}",
            "users": [
                {"user_id": "transcript_id"}, ...
            ]
        }

        Args:
            meeting_id: Meeting ID (16 chars)
            user_transcript_mapping: Dictionary mapping user_id to transcript_id
            meeting_summary_path: Optional path to the meeting summary file
        """
        # Validate input
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        # Build the new format
        users_array = [
            {user_id: transcript_id} for user_id, transcript_id in user_transcript_mapping.items()
        ]

        transcript_ids_data = {
            "meeting_summary": meeting_summary_path or "",
            "users": users_array,
        }

        timestamp = get_current_timestamp_est()

        # Build update query
        stmt = (
            update(MeetingModel)
            .where(MeetingModel.id == meeting_id)
            .values(transcript_ids=transcript_ids_data, updated_at=timestamp)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Updated meeting {meeting_id} transcript_ids with {len(users_array)} user transcripts"
        )

    async def check_and_update_meeting_status(
        self, meeting_id: str, is_recording: bool
    ) -> MeetingStatus:
        """
        Check transcode status and update meeting status accordingly.

        Logic:
        - If is_recording=True: status = RECORDING
        - If is_recording=False and transcodes pending: status = PROCESSING
        - If is_recording=False and all transcodes done: status = COMPLETED

        Args:
            meeting_id: Meeting ID
            is_recording: Whether recording is still active

        Returns:
            The new MeetingStatus that was set
        """
        # If still recording, keep RECORDING status
        if is_recording:
            await self.update_meeting_status(meeting_id, MeetingStatus.RECORDING)
            return MeetingStatus.RECORDING

        # Recording stopped - check transcode status
        temp_recordings = await self.get_temp_recordings_for_meeting(meeting_id)

        # Count pending transcodes
        pending_count = sum(
            1
            for rec in temp_recordings
            if rec["transcode_status"]
            in [TranscodeStatus.QUEUED.value, TranscodeStatus.IN_PROGRESS.value]
        )

        if pending_count > 0:
            # Still processing
            await self.update_meeting_status(meeting_id, MeetingStatus.PROCESSING)
            await self.services.logging_service.info(
                f"Meeting {meeting_id} has {pending_count} pending transcodes - status: PROCESSING"
            )
            return MeetingStatus.PROCESSING
        else:
            # All done - update status to COMPLETED
            await self.update_meeting_status(meeting_id, MeetingStatus.COMPLETED)
            await self.services.logging_service.info(
                f"Meeting {meeting_id} all transcodes complete - status: COMPLETED"
            )

            # Create transcription job for this meeting
            await self._create_transcription_job_for_meeting(meeting_id)

            return MeetingStatus.COMPLETED

    async def create_transcription_job_for_completed_meeting(self, meeting_id: str) -> None:
        """
        Create a transcription job for a completed meeting after persistent recordings are ready.

        This is the public method called after all persistent recordings have been created.
        It updates the meeting status to TRANSCRIBING and creates the transcription job.

        Args:
            meeting_id: Meeting ID
        """
        try:
            # Update meeting status to TRANSCRIBING
            await self.update_meeting_status(meeting_id, MeetingStatus.TRANSCRIBING)
            await self.services.logging_service.info(
                f"Meeting {meeting_id} status updated to TRANSCRIBING"
            )

            # Create the transcription job
            await self._create_transcription_job_for_meeting(meeting_id)

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to create transcription job for meeting {meeting_id}: {type(e).__name__}: {str(e)}"
            )

    async def _create_transcription_job_for_meeting(self, meeting_id: str) -> None:
        """
        Create a transcription job for a completed meeting.

        This is called automatically when a meeting's status is updated to TRANSCRIBING.
        It gathers all recordings for the meeting and creates a transcription job.

        Args:
            meeting_id: Meeting ID
        """
        # Check if transcription job manager is available
        if not self.services.transcription_job_manager:
            await self.services.logging_service.warning(
                f"Transcription job manager not available, skipping job creation for meeting {meeting_id}"
            )
            return

        try:
            # Get all persistent recordings for this meeting
            recordings = await self.get_persistent_recordings_for_meeting(meeting_id)

            if not recordings:
                await self.services.logging_service.warning(
                    f"No recordings found for meeting {meeting_id}, skipping transcription job creation"
                )
                return

            # Extract recording IDs and user IDs
            recording_ids = [rec["id"] for rec in recordings]
            user_ids = list({rec["user_id"] for rec in recordings})  # Deduplicate user IDs

            # Create and queue the transcription job
            job_id = (
                await self.services.transcription_job_manager.create_and_queue_transcription_job(
                    meeting_id=meeting_id, recording_ids=recording_ids, user_ids=user_ids
                )
            )

            await self.services.logging_service.info(
                f"Created transcription job {job_id} for meeting {meeting_id} "
                f"with {len(recording_ids)} recordings from {len(user_ids)} users"
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to create transcription job for meeting {meeting_id}: {type(e).__name__}: {str(e)}"
            )

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

    async def get_recording_by_id(self, recording_id: str) -> dict | None:
        """
        Get a specific recording by its ID.

        Args:
            recording_id: The recording ID

        Returns:
            Recording dictionary or None if not found
        """
        # Validate input
        if len(recording_id) != 16:
            raise ValueError("recording_id must be 16 characters long")

        # Build and execute query
        query = select(RecordingModel).where(RecordingModel.id == recording_id)
        results = await self.server.sql_client.execute(query)

        return results[0] if results else None

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

    # -------------------------------------------------------------- #
    # Job Status Methods
    # -------------------------------------------------------------- #

    async def create_job_status(
        self,
        job_id: str,
        job_type: JobsType,
        meeting_id: str,
        created_at,
        status: JobsStatus,
    ) -> None:
        """
        Create a new job status entry.

        Args:
            job_id: Unique job ID (16 chars)
            job_type: Type of the job (JobsType enum)
            meeting_id: Meeting ID (16 chars)
            created_at: Timestamp when the job was created
            status: Initial status of the job (JobsStatus enum)
        """
        # Validate inputs
        if len(job_id) != 16:
            raise ValueError("job_id must be 16 characters long")
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        job_status = JobsStatusModel(
            id=job_id,
            type=job_type.value,
            meeting_id=meeting_id,
            created_at=created_at,
            started_at=None,
            finished_at=None,
            status=status.value,
            error_log=None,
        )

        # Convert to dict for insertion
        data = {
            "id": job_status.id,
            "type": job_status.type,
            "meeting_id": job_status.meeting_id,
            "created_at": job_status.created_at,
            "started_at": job_status.started_at,
            "finished_at": job_status.finished_at,
            "status": job_status.status,
            "error_log": job_status.error_log,
        }

        # Build and execute insert statement
        stmt = insert(JobsStatusModel).values(**data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Created job status entry: {job_id} of type {job_type.value} for meeting {meeting_id}"
        )

    async def update_job_status(
        self,
        job_id: str,
        status: JobsStatus,
        started_at=None,
        finished_at=None,
        error_log: str | None = None,
    ) -> None:
        """
        Update a job status entry.

        Args:
            job_id: Unique job ID (16 chars)
            status: New status of the job (JobsStatus enum)
            started_at: Optional timestamp when the job started
            finished_at: Optional timestamp when the job finished
            error_log: Optional error log information
        """
        # Validate input
        if len(job_id) != 16:
            raise ValueError("job_id must be 16 characters long")

        # Build update values
        update_values = {"status": status.value}
        if started_at is not None:
            update_values["started_at"] = started_at
        if finished_at is not None:
            update_values["finished_at"] = finished_at
        if error_log is not None:
            update_values["error_log"] = error_log

        # Build and execute update statement
        stmt = update(JobsStatusModel).where(JobsStatusModel.id == job_id).values(**update_values)

        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.debug(f"Updated job status {job_id} to {status.value}")

    async def get_job_status(self, job_id: str) -> dict | None:
        """
        Get job status by job ID.

        Args:
            job_id: Unique job ID (16 chars)

        Returns:
            Dictionary with job status information or None if not found
        """
        # Validate input
        if len(job_id) != 16:
            raise ValueError("job_id must be 16 characters long")

        # Build and execute query
        query = select(JobsStatusModel).where(JobsStatusModel.id == job_id)
        result = await self.server.sql_client.execute(query)
        row = result.fetchone()

        if not row:
            return None

        return {
            "job_id": row.id,
            "type": row.type,
            "meeting_id": row.meeting_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "status": row.status,
            "error_log": row.error_log,
        }

    async def get_jobs_for_meeting(self, meeting_id: str) -> list[dict]:
        """
        Get all jobs for a specific meeting.

        Args:
            meeting_id: Meeting ID (16 chars)

        Returns:
            List of job status dictionaries
        """
        # Validate input
        if len(meeting_id) != MEETING_UUID_LENGTH:
            raise ValueError(f"meeting_id must be {MEETING_UUID_LENGTH} characters long")

        # Build and execute query
        query = select(JobsStatusModel).where(JobsStatusModel.meeting_id == meeting_id)
        results = await self.server.sql_client.execute(query)

        jobs = []
        for row in results:
            jobs.append(
                {
                    "job_id": row.id,
                    "type": row.type,
                    "meeting_id": row.meeting_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    "status": row.status,
                    "error_log": row.error_log,
                }
            )

        return jobs
