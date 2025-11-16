"""
Transcription Job Manager Service.

This service manages a queue of transcription jobs that are created when
recording sessions are completed. It uses an event-based job queue that:
- Processes one transcription job at a time
- Automatically activates when jobs are added
- Remains idle when no jobs are pending
- Tracks job status in the SQL database
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from source.services.common.job import Job, JobQueue
from source.services.manager import Manager
from source.server.sql_models import JobsStatus, JobsType
from source.utils import generate_16_char_uuid, get_current_timestamp_est


@dataclass
class TranscriptionJob(Job):
    """
    A job representing a transcription task for a meeting.

    Attributes:
        meeting_id: ID of the meeting to transcribe
        recording_ids: List of recording IDs to transcribe
        user_ids: List of user IDs associated with the recordings
        services: Reference to ServicesManager for accessing services
    """

    meeting_id: str = ""
    recording_ids: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    services: "ServicesManager" = None  # type: ignore

    # -------------------------------------------------------------- #
    # Job Execution
    # -------------------------------------------------------------- #

    async def execute(self) -> None:
        """
        Execute the transcription job.

        This will:
        1. Fetch all recording files for the meeting
        2. Send them to the transcription service (whisper)
        3. Process and store the results to data/transcriptions/storage/
        """
        if not self.services:
            raise RuntimeError("ServicesManager not provided to TranscriptionJob")

        await self.services.logging_service.info(
            f"Starting transcription for meeting {self.meeting_id} with {len(self.recording_ids)} recordings"
        )

        # Process each recording
        for recording_id in self.recording_ids:
            try:
                await self._transcribe_recording(recording_id)
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to transcribe recording {recording_id}: {type(e).__name__}: {str(e)}"
                )
                # Continue with other recordings even if one fails
                continue

        await self.services.logging_service.info(
            f"Completed transcription for meeting {self.meeting_id}"
        )

    # -------------------------------------------------------------- #
    # Transcription Methods
    # -------------------------------------------------------------- #

    async def _transcribe_recording(self, recording_id: str) -> None:
        """
        Transcribe a single recording file.

        Args:
            recording_id: The recording ID to transcribe
        """
        import os

        # Get recording metadata from SQL
        recording = await self.services.sql_recording_service_manager.get_recording_by_id(
            recording_id
        )

        if not recording:
            await self.services.logging_service.warning(
                f"Recording {recording_id} not found in database"
            )
            return

        user_id = recording["user_id"]
        filename = recording["filename"]

        await self.services.logging_service.info(
            f"Transcribing recording {recording_id} for user {user_id}: {filename}"
        )

        # Get full path to recording file
        storage_path = self.services.recording_file_service_manager.get_persistent_storage_path()
        audio_file_path = os.path.join(storage_path, filename)

        # Check if file exists
        if not os.path.exists(audio_file_path):
            await self.services.logging_service.error(
                f"Recording file not found: {audio_file_path}"
            )
            return

        # Send to Whisper for transcription
        try:
            transcript_text = await self.services.server.whisper_server_client.inference(
                audio_path=audio_file_path,
                word_timestamps=True,
                response_format="verbose_json",
                temperature="0.0",
                temperature_inc="0.2",
                language="en",
            )

            await self.services.logging_service.info(
                f"Successfully transcribed recording {recording_id}"
            )

            # Prepare transcript data
            transcript_data = {
                "meeting_id": self.meeting_id,
                "user_id": user_id,
                "recording_id": recording_id,
                "whisper_data": transcript_text,
                "created_at": get_current_timestamp_est().isoformat(),
            }

            # Save transcription to file and database
            # File will be saved as: data/transcriptions/storage/transcript_{meeting_id}_{user_id}_{transcript_id}.json
            transcript_id, transcript_filename = (
                await self.services.transcription_file_service_manager.save_transcription(
                    transcript_data=transcript_data,
                    meeting_id=self.meeting_id,
                    user_id=user_id,
                )
            )

            await self.services.logging_service.info(
                f"Saved transcription {transcript_id} to {transcript_filename}"
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to transcribe or save recording {recording_id}: {e}"
            )
            raise


class BaseTranscriptionJobManagerService(Manager):
    """Base class for transcription job manager service."""

    async def create_and_queue_transcription_job(
        self, meeting_id: str, recording_ids: list[str], user_ids: list[str]
    ) -> str:
        """Create a new transcription job and add it to the queue."""
        pass

    async def get_job_status(self, job_id: str) -> dict:
        """Get the status of a specific job."""
        pass

    async def get_queue_statistics(self) -> dict:
        """Get statistics about the job queue."""
        pass


class TranscriptionJobManagerService(BaseTranscriptionJobManagerService):
    """
    Service for managing transcription job queue.

    This service handles the creation and processing of transcription jobs
    when recording sessions are completed. It uses an event-based job queue
    that processes one job at a time.
    """

    def __init__(self, context: Context):
        """
        Initialize the transcription job manager.

        Args:
            context: Application context
        """
        super().__init__(context)
        self._job_queue: JobQueue[TranscriptionJob] | None = None
        self._active_jobs: dict[str, TranscriptionJob] = {}

    async def on_start(self, services: ServicesManager) -> None:
        """
        Initialize the transcription job manager.

        Args:
            services: Services manager instance
        """
        await super().on_start(services)

        # Initialize the job queue with callbacks
        self._job_queue = JobQueue[TranscriptionJob](
            max_retries=2,  # Retry failed jobs up to 2 times
            on_job_started=self._on_job_started,
            on_job_complete=self._on_job_complete,
            on_job_failed=self._on_job_failed,
        )

        await self.services.logging_service.info("Transcription Job Manager initialized")

    async def on_close(self) -> None:
        """Cleanup when service is shutting down."""
        if self._job_queue and self._job_queue.is_running():
            await self.services.logging_service.info(
                "Shutting down transcription job queue, waiting for current job to complete..."
            )
            await self._job_queue.stop(wait_for_completion=True)

        await super().on_close()

    # -------------------------------------------------------------- #
    # Public API
    # -------------------------------------------------------------- #

    async def create_and_queue_transcription_job(
        self, meeting_id: str, recording_ids: list[str], user_ids: list[str]
    ) -> str:
        """
        Create a new transcription job and add it to the queue.

        This method also creates a corresponding entry in the SQL database
        to track the job's progress.

        Args:
            meeting_id: ID of the meeting to transcribe
            recording_ids: List of recording IDs associated with the meeting
            user_ids: List of user IDs who participated in the meeting

        Returns:
            The job ID of the created transcription job
        """
        # Generate unique job ID
        job_id = generate_16_char_uuid()

        # Create the job
        job = TranscriptionJob(
            job_id=job_id,
            meeting_id=meeting_id,
            recording_ids=recording_ids,
            user_ids=user_ids,
            services=self.services,
            metadata={
                "recording_count": len(recording_ids),
                "user_count": len(user_ids),
            },
        )

        # Store job in active jobs
        self._active_jobs[job_id] = job

        # Create SQL entry for the job
        await self._create_sql_job_entry(job)

        # Add job to queue (this will auto-start the worker if needed)
        await self._job_queue.add_job(job)

        await self.services.logging_service.info(
            f"Created transcription job {job_id} for meeting {meeting_id} "
            f"with {len(recording_ids)} recordings"
        )

        return job_id

    async def get_job_status(self, job_id: str) -> dict:
        """
        Get the status of a specific job.

        Args:
            job_id: ID of the job to query

        Returns:
            Dictionary with job status information
        """
        if job_id not in self._active_jobs:
            # Try to fetch from database
            if self.services.sql_recording_service_manager:
                db_job = await self.services.sql_recording_service_manager.get_job_status(job_id)
                if db_job:
                    return db_job

            return {"error": "Job not found"}

        job = self._active_jobs[job_id]
        return {
            "job_id": job.job_id,
            "meeting_id": job.meeting_id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "error_message": job.error_message,
            "metadata": job.metadata,
        }

    async def get_queue_statistics(self) -> dict:
        """
        Get statistics about the job queue.

        Returns:
            Dictionary with queue statistics
        """
        if not self._job_queue:
            return {"error": "Job queue not initialized"}

        stats = self._job_queue.get_statistics()
        stats["active_jobs_count"] = len(self._active_jobs)
        return stats

    # -------------------------------------------------------------- #
    # Private Methods
    # -------------------------------------------------------------- #

    async def _create_sql_job_entry(self, job: TranscriptionJob) -> None:
        """
        Create a SQL database entry for the transcription job.

        Args:
            job: The transcription job to create an entry for
        """
        if not self.services.sql_recording_service_manager:
            await self.services.logging_service.warning(
                "SQL recording service not available, skipping job entry creation"
            )
            return

        try:
            await self.services.sql_recording_service_manager.create_job_status(
                job_id=job.job_id,
                job_type=JobsType.TRANSCRIBING,
                meeting_id=job.meeting_id,
                created_at=job.created_at,
                status=JobsStatus.PENDING,
            )
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to create SQL entry for transcription job {job.job_id}: {e}"
            )

    async def _update_sql_job_status(self, job: TranscriptionJob) -> None:
        """
        Update the SQL database entry for the transcription job.

        Args:
            job: The transcription job to update
        """
        if not self.services.sql_recording_service_manager:
            return

        try:
            # Map Job status to SQL JobsStatus
            from source.server.sql_models import JobsStatus as SQLJobStatus

            status_map = {
                "pending": SQLJobStatus.PENDING,
                "in_progress": SQLJobStatus.IN_PROGRESS,
                "completed": SQLJobStatus.COMPLETED,
                "failed": SQLJobStatus.FAILED,
                "cancelled": SQLJobStatus.SKIPPED,
            }

            sql_status = status_map.get(job.status.value, SQLJobStatus.PENDING)

            await self.services.sql_recording_service_manager.update_job_status(
                job_id=job.job_id,
                status=sql_status,
                started_at=job.started_at,
                finished_at=job.finished_at,
                error_log=job.error_message if job.error_message else None,
            )
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update SQL entry for transcription job {job.job_id}: {e}"
            )

    # -------------------------------------------------------------- #
    # Job Queue Callbacks
    # -------------------------------------------------------------- #

    async def _on_job_started(self, job: TranscriptionJob) -> None:
        """
        Callback when a job starts processing.

        Args:
            job: The job that started
        """
        await self.services.logging_service.info(
            f"Started transcription job {job.job_id} for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

    async def _on_job_complete(self, job: TranscriptionJob) -> None:
        """
        Callback when a job completes successfully.

        Args:
            job: The job that completed
        """
        await self.services.logging_service.info(
            f"Completed transcription job {job.job_id} for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

        # Update meeting status to COMPLETED
        if self.services.sql_recording_service_manager:
            try:
                from source.server.sql_models import MeetingStatus

                await self.services.sql_recording_service_manager.update_meeting_status(
                    meeting_id=job.meeting_id, status=MeetingStatus.COMPLETED
                )
                await self.services.logging_service.info(
                    f"Meeting {job.meeting_id} status updated to COMPLETED after transcription"
                )
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to update meeting {job.meeting_id} status to COMPLETED: {e}"
                )

        # Clean up from active jobs after a delay (keep in memory for status queries)
        # We keep it for a while in case status is queried right after completion

    async def _on_job_failed(self, job: TranscriptionJob) -> None:
        """
        Callback when a job fails.

        Args:
            job: The job that failed
        """
        await self.services.logging_service.error(
            f"Failed transcription job {job.job_id} for meeting {job.meeting_id}: "
            f"{job.error_message}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

        # Optionally: Send notification to admin or user about failed transcription
