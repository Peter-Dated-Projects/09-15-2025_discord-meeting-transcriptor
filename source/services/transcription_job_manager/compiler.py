"""
Transcription Compilation Job Manager Service.

This service manages a queue of transcription compilation jobs that are created
when transcription tasks are completed. It compiles individual user transcriptions
into a unified, normalized format with proper timestamp ordering and speaker attribution.

The normalized format is:
{
    "timestamp": {
        "start_time": "start_time",
        "end_time": "end_time",
    },
    "speaker": {
        "user_id": "discord_user_id",
        "user_transcription_file": "file_name.json",
    },
    "content": "text content"
}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from source.server.sql_models import JobsStatus, JobsType
from source.services.common.job import Job, JobQueue
from source.services.manager import Manager
from source.utils import generate_16_char_uuid, get_current_timestamp_est


@dataclass
class TranscriptionCompilationJob(Job):
    """
    A job representing a transcription compilation task for a meeting.

    This job takes multiple individual user transcription files and compiles them
    into a single, time-ordered compilation with normalized format.

    Attributes:
        meeting_id: ID of the meeting to compile transcriptions for
        transcript_ids: List of transcript IDs to compile
        user_ids: List of user IDs associated with the transcripts
        services: Reference to ServicesManager for accessing services
    """

    meeting_id: str = ""
    transcript_ids: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    services: ServicesManager = None  # type: ignore

    # -------------------------------------------------------------- #
    # Job Execution
    # -------------------------------------------------------------- #

    async def execute(self) -> None:
        """
        Execute the transcription compilation job.

        This will:
        1. Fetch all transcription files for the meeting
        2. Parse and normalize each transcription into the standard format
        3. Merge and sort all transcriptions by timestamp
        4. Save the compiled result to data/compilations/storage/
        """
        if not self.services:
            raise RuntimeError("ServicesManager not provided to TranscriptionCompilationJob")

        await self.services.logging_service.info(
            f"Starting transcription compilation for meeting {self.meeting_id} "
            f"with {len(self.transcript_ids)} transcripts"
        )

        try:
            # Step 1: Retrieve all transcription metadata from SQL
            transcription_metadata = await self.services.transcription_file_service_manager.get_transcriptions_by_meeting(
                self.meeting_id
            )

            if not transcription_metadata:
                await self.services.logging_service.warning(
                    f"No transcriptions found for meeting {self.meeting_id}"
                )
                return

            await self.services.logging_service.info(
                f"Retrieved {len(transcription_metadata)} transcription files for meeting {self.meeting_id}"
            )

            # Step 2: Load all transcription JSON files and extract meaningful data
            all_segments = []

            for metadata in transcription_metadata:
                transcript_id = metadata["id"]
                user_id = metadata["user_id"]
                filename = metadata["filename"]

                await self.services.logging_service.info(
                    f"Processing transcription {transcript_id} for user {user_id}: {filename}"
                )

                # Retrieve the full transcription data
                transcription_data = (
                    await self.services.transcription_file_service_manager.retrieve_transcription(
                        transcript_id
                    )
                )

                if not transcription_data:
                    await self.services.logging_service.warning(
                        f"Failed to retrieve transcription data for {transcript_id}, skipping..."
                    )
                    continue

                # Extract segments from whisper data and normalize to standard format
                whisper_data = transcription_data.get("whisper_data", {})
                segments = whisper_data.get("segments", [])

                for segment in segments:
                    # Extract only the meaningful data per text segment
                    normalized_segment = {
                        "timestamp": {
                            "start_time": segment.get("start", 0.0),
                            "end_time": segment.get("end", 0.0),
                        },
                        "speaker": {
                            "user_id": user_id,
                            "user_transcription_file": filename,
                        },
                        "content": segment.get("text", "").strip(),
                    }
                    all_segments.append(normalized_segment)

            # Step 3: Sort all segments by start time
            all_segments.sort(key=lambda x: x["timestamp"]["start_time"])

            await self.services.logging_service.info(
                f"Compiled {len(all_segments)} segments from {len(transcription_metadata)} transcriptions"
            )

            # Step 4: Create the new JSON object with compiled data
            compilation_result = {
                "meeting_id": self.meeting_id,
                "compiled_at": get_current_timestamp_est().isoformat(),
                "transcript_count": len(transcription_metadata),
                "user_ids": list({m["user_id"] for m in transcription_metadata}),
                "segment_count": len(all_segments),
                "segments": all_segments,
            }

            # Step 5: Save the compilation to file
            await self._save_compilation(compilation_result)

            await self.services.logging_service.info(
                f"Completed transcription compilation for meeting {self.meeting_id}"
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to compile transcriptions for meeting {self.meeting_id}: {str(e)}"
            )
            raise

    async def _save_compilation(self, compilation_data: dict) -> str:
        """
        Save the compiled transcription JSON object to a file and database.

        Args:
            compilation_data: The compiled transcription data

        Returns:
            The compiled transcript ID
        """
        import asyncio
        import json
        import os
        from datetime import datetime

        import aiofiles
        from sqlalchemy import insert

        from source.server.sql_models import CompiledTranscriptsModel
        from source.utils import calculate_file_sha256, generate_16_char_uuid

        # Create compilations directory if it doesn't exist
        base_path = "assets/data/transcriptions"
        compilations_path = os.path.join(base_path, "compilations")
        storage_path = os.path.join(compilations_path, "storage")

        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, compilations_path):
            await loop.run_in_executor(None, os.makedirs, compilations_path)
        if not await loop.run_in_executor(None, os.path.exists, storage_path):
            await loop.run_in_executor(None, os.makedirs, storage_path)

        # Generate filename: transcript_{meeting_id}.json
        filename = f"transcript_{self.meeting_id}.json"
        file_path = os.path.join(storage_path, filename)

        # Save the JSON object to file
        async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
            await f.write(json.dumps(compilation_data, indent=2, ensure_ascii=False))

        await self.services.logging_service.info(
            f"Saved compilation to {filename} ({len(compilation_data['segments'])} segments)"
        )

        # Calculate SHA256 hash
        sha256_hash = await calculate_file_sha256(file_path)

        # Generate compiled transcript ID
        compiled_transcript_id = generate_16_char_uuid()

        # Create SQL entry for compiled transcript
        created_at = datetime.now()

        stmt = insert(CompiledTranscriptsModel).values(
            id=compiled_transcript_id,
            created_at=created_at,
            meeting_id=self.meeting_id,
            sha256=sha256_hash,
            transcript_filename=filename,
        )
        await self.services.server.sql_client.execute(stmt)

        await self.services.logging_service.info(
            f"Created SQL entry for compiled transcript: {compiled_transcript_id}"
        )

        return compiled_transcript_id


class BaseTranscriptionCompilationJobManagerService(Manager):
    """Base class for transcription compilation job manager service."""

    async def create_and_queue_compilation_job(
        self, meeting_id: str, transcript_ids: list[str], user_ids: list[str]
    ) -> str:
        """Create a new transcription compilation job and add it to the queue."""
        pass

    async def get_job_status(self, job_id: str) -> dict:
        """Get the status of a specific job."""
        pass

    async def get_queue_statistics(self) -> dict:
        """Get statistics about the job queue."""
        pass


class TranscriptionCompilationJobManagerService(BaseTranscriptionCompilationJobManagerService):
    """
    Service for managing transcription compilation job queue.

    This service handles the creation and processing of compilation jobs
    when transcription tasks are completed. It uses an event-based job queue
    that processes one job at a time.
    """

    def __init__(self, context: Context):
        """
        Initialize the transcription compilation job manager.

        Args:
            context: Application context
        """
        super().__init__(context)
        self._job_queue: JobQueue[TranscriptionCompilationJob] | None = None
        self._active_jobs: dict[str, TranscriptionCompilationJob] = {}

    async def on_start(self, services: ServicesManager) -> None:
        """
        Initialize the transcription compilation job manager.

        Args:
            services: Services manager instance
        """
        await super().on_start(services)

        # Initialize the job queue with callbacks
        self._job_queue = JobQueue[TranscriptionCompilationJob](
            max_retries=2,  # Retry failed jobs up to 2 times
            on_job_started=self._on_job_started,
            on_job_complete=self._on_job_complete,
            on_job_failed=self._on_job_failed,
        )

        await self.services.logging_service.info(
            "Transcription Compilation Job Manager initialized"
        )

    async def on_close(self) -> None:
        """Cleanup when service is shutting down."""
        if self._job_queue and self._job_queue.is_running():
            await self.services.logging_service.info(
                "Shutting down transcription compilation job queue, "
                "waiting for current job to complete..."
            )
            await self._job_queue.stop(wait_for_completion=True)

        await super().on_close()

    # -------------------------------------------------------------- #
    # Public API
    # -------------------------------------------------------------- #

    async def create_and_queue_compilation_job(
        self, meeting_id: str, transcript_ids: list[str], user_ids: list[str]
    ) -> str:
        """
        Create a new transcription compilation job and add it to the queue.

        This method also creates a corresponding entry in the SQL database
        to track the job's progress.

        Args:
            meeting_id: ID of the meeting to compile transcriptions for
            transcript_ids: List of transcript IDs associated with the meeting
            user_ids: List of user IDs who participated in the meeting

        Returns:
            The job ID of the created compilation job
        """
        # Generate unique job ID
        job_id = generate_16_char_uuid()

        # Create the job
        job = TranscriptionCompilationJob(
            job_id=job_id,
            meeting_id=meeting_id,
            transcript_ids=transcript_ids,
            user_ids=user_ids,
            services=self.services,
            metadata={
                "transcript_count": len(transcript_ids),
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
            f"Created transcription compilation job {job_id} for meeting {meeting_id} "
            f"with {len(transcript_ids)} transcripts"
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

    async def _create_sql_job_entry(self, job: TranscriptionCompilationJob) -> None:
        """
        Create a SQL database entry for the transcription compilation job.

        Args:
            job: The transcription compilation job to create an entry for
        """
        if not self.services.sql_recording_service_manager:
            await self.services.logging_service.warning(
                "SQL recording service not available, skipping job entry creation"
            )
            return

        try:
            await self.services.sql_recording_service_manager.create_job_status(
                job_id=job.job_id,
                job_type=JobsType.COMPILING,
                meeting_id=job.meeting_id,
                created_at=job.created_at,
                status=JobsStatus.PENDING,
            )
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to create SQL entry for compilation job {job.job_id}: {e}"
            )

    async def _update_sql_job_status(self, job: TranscriptionCompilationJob) -> None:
        """
        Update the SQL database entry for the transcription compilation job.

        Args:
            job: The transcription compilation job to update
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
                f"Failed to update SQL entry for compilation job {job.job_id}: {e}"
            )

    # -------------------------------------------------------------- #
    # Job Queue Callbacks
    # -------------------------------------------------------------- #

    async def _on_job_started(self, job: TranscriptionCompilationJob) -> None:
        """
        Callback when a job starts processing.

        Args:
            job: The job that started
        """
        await self.services.logging_service.info(
            f"Started transcription compilation job {job.job_id} for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

    async def _on_job_complete(self, job: TranscriptionCompilationJob) -> None:
        """
        Callback when a job completes successfully.

        Args:
            job: The job that completed
        """
        await self.services.logging_service.info(
            f"Completed transcription compilation job {job.job_id} " f"for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

        # Trigger summarization job if summarization job manager is available
        if self.services.summarization_job_manager and job.transcript_ids:
            try:
                # We need to get the compiled_transcript_id from the compilation result
                # For now, we'll construct it based on the meeting_id
                compiled_transcript_id = f"compiled_{job.meeting_id}"

                await self.services.summarization_job_manager.create_and_queue_summarization_job(
                    meeting_id=job.meeting_id,
                    compiled_transcript_id=compiled_transcript_id,
                    transcript_ids=job.transcript_ids,
                )
            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to create summarization job for meeting {job.meeting_id}: {e}"
                )
        elif not job.transcript_ids:
            await self.services.logging_service.warning(
                f"No transcript IDs found for meeting {job.meeting_id}, skipping summarization job"
            )

        # Send DM notifications to all users who participated in the meeting
        await self._send_compilation_notifications(job)

    async def _send_compilation_notifications(self, job: TranscriptionCompilationJob) -> None:
        """
        Send DM notifications to all users who participated in the meeting.

        Args:
            job: The completed compilation job
        """
        try:
            # Import required modules
            import discord

            from source.utils import BotUtils

            # Get meeting data
            meeting_data = await self.services.sql_recording_service_manager.get_meeting(
                meeting_id=job.meeting_id
            )

            if not meeting_data:
                await self.services.logging_service.warning(
                    f"Could not find meeting data for {job.meeting_id}, skipping notifications"
                )
                return

            # Get guild data
            if not self.services.context.bot:
                await self.services.logging_service.warning(
                    "Bot instance not available, cannot send DM notifications"
                )
                return

            try:
                guild_data = await self.services.context.bot.fetch_guild(
                    int(meeting_data["guild_id"])
                )
            except (ValueError, discord.NotFound, discord.HTTPException) as e:
                await self.services.logging_service.error(
                    f"Failed to fetch guild data: {e}, skipping notifications"
                )
                return

            # Prepare guild info
            guild_name = (
                guild_data.name
                if hasattr(guild_data, "name")
                else guild_data.get("name", "Unknown Guild")
            )

            guild_icon_url = None
            if hasattr(guild_data, "icon") and guild_data.icon:
                guild_icon_url = guild_data.icon.url
            elif isinstance(guild_data, dict) and guild_data.get("icon"):
                guild_icon_url = guild_data["icon"]

            # Get meeting timestamp
            created_at = meeting_data.get("started_at")
            if created_at and hasattr(created_at, "timestamp"):
                created_at_timestamp = int(created_at.timestamp())
            elif created_at:
                created_at_timestamp = int(created_at)
            else:
                import datetime

                created_at_timestamp = int(datetime.datetime.now().timestamp())

            # Get requested_by user info
            requested_by_id = meeting_data.get("requested_by", "Unknown")
            requested_by_user_name = None
            footer_icon_url = None

            try:
                requested_user = await self.services.context.bot.fetch_user(int(requested_by_id))
                if requested_user and requested_user.avatar:
                    footer_icon_url = requested_user.avatar.url
                    requested_by_user_name = requested_user.name
            except (ValueError, discord.NotFound, discord.HTTPException):
                pass

            # Create embed for each user
            for user_id in job.user_ids:
                try:
                    embed = discord.Embed(
                        title=f"**Meeting Finished**: Meeting in `{guild_name}`",
                        description=(
                            "**✅ Your recording has been transcribed and compiled!**\n\n"
                            "The meeting transcription is now available."
                        ),
                        color=discord.Color.green(),
                    )

                    if guild_icon_url:
                        embed.set_thumbnail(url=guild_icon_url)

                    embed.add_field(
                        name="Recording Date",
                        value=f"<t:{created_at_timestamp}:F>",
                        inline=False,
                    )

                    embed.add_field(
                        name="Compilation",
                        value=f"`transcript_{job.meeting_id}.json`",
                        inline=False,
                    )

                    embed.set_footer(
                        text=f"Requested by {requested_by_user_name or requested_by_id}",
                        icon_url=footer_icon_url,
                    )

                    # Send DM
                    success = await BotUtils.send_dm(
                        self.services.context.bot, user_id, embed=embed
                    )

                    if success:
                        await self.services.logging_service.info(
                            f"Sent compilation notification to user {user_id} for meeting {job.meeting_id}"
                        )
                    else:
                        await self.services.logging_service.warning(
                            f"Failed to send compilation notification to user {user_id}"
                        )

                except Exception as e:
                    await self.services.logging_service.error(
                        f"Error sending notification to user {user_id}: {e}"
                    )

        except Exception as e:
            await self.services.logging_service.error(
                f"Error in _send_compilation_notifications: {e}"
            )

    async def _on_job_failed(self, job: TranscriptionCompilationJob) -> None:
        """
        Callback when a job fails.

        Args:
            job: The job that failed
        """
        await self.services.logging_service.error(
            f"Failed transcription compilation job {job.job_id} "
            f"for meeting {job.meeting_id}: {job.error_message}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

        # Optionally: Send notification to admin or user about failed compilation
