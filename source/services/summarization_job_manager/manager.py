"""
Summarization Job Manager Service.

This service manages a queue of summarization jobs that are created when
transcription compilation tasks are completed. It uses an event-based job queue that:
- Processes one summarization job at a time
- Automatically activates when jobs are added
- Remains idle when no jobs are pending
- Tracks job status in the SQL database
- Uses recursive summarization to handle large transcripts
- Updates individual transcription files with summaries and summary_layers
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
class SummarizationJob(Job):
    """
    A job representing a summarization task for a compiled meeting transcript.

    This job takes a compiled transcription and creates recursive summaries,
    then updates all individual transcription files with the generated summaries.

    Attributes:
        meeting_id: ID of the meeting to summarize
        compiled_transcript_id: ID of the compiled transcript to summarize
        transcript_ids: List of individual transcript IDs to update with summaries
        user_ids: List of user IDs who participated in the meeting
        services: Reference to ServicesManager for accessing services
    """

    meeting_id: str = ""
    compiled_transcript_id: str = ""
    transcript_ids: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    services: ServicesManager = None  # type: ignore

    # -------------------------------------------------------------- #
    # Job Execution
    # -------------------------------------------------------------- #

    async def execute(self) -> None:
        """
        Execute the summarization job.

        This will:
        1. Load the compiled transcript
        2. Extract raw text from segments
        3. Perform recursive summarization using Ollama
        4. Store summary layers and final summary
        5. Update all individual transcription files with the summaries
        """
        if not self.services:
            raise RuntimeError("ServicesManager not provided to SummarizationJob")

        await self.services.logging_service.info(
            f"Starting summarization for meeting {self.meeting_id}"
        )

        try:
            # Step 1: Retrieve the compiled transcript
            compiled_transcript = await self._load_compiled_transcript()
            if not compiled_transcript:
                await self.services.logging_service.warning(
                    f"No compiled transcript found for meeting {self.meeting_id}"
                )
                return

            # Step 2: Extract raw text from segments
            raw_text = self._extract_raw_text(compiled_transcript)
            await self.services.logging_service.info(
                f"Extracted {len(raw_text.split())} words from compiled transcript"
            )

            # Step 3: Perform recursive summarization WITH GPU LOCK
            async with self.services.gpu_resource_manager.acquire_lock(
                job_type="summarization",
                job_id=self.job_id,
                metadata={
                    "meeting_id": self.meeting_id,
                    "compiled_transcript_id": self.compiled_transcript_id,
                },
            ):
                # GPU is now locked - perform summarization
                summary_layers, final_summary = await self._recursive_summarization(raw_text)

                await self.services.logging_service.info(
                    f"Generated {len(summary_layers)} summary layers with "
                    f"final summary of {len(final_summary.split())} words"
                )

            # GPU lock automatically released here

            # Step 4: Update all individual transcription files with summaries
            await self._update_transcription_files(summary_layers, final_summary)

            await self.services.logging_service.info(
                f"Completed summarization for meeting {self.meeting_id}"
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to summarize meeting {self.meeting_id}: {str(e)}"
            )
            raise

    # -------------------------------------------------------------- #
    # Summarization Methods
    # -------------------------------------------------------------- #

    async def _load_compiled_transcript(self) -> dict | None:
        """
        Load the compiled transcript from storage.

        Returns:
            The compiled transcript data or None if not found
        """
        import asyncio
        import json
        import os

        import aiofiles

        # Construct file path
        base_path = "assets/data/transcriptions"
        compilations_path = os.path.join(base_path, "compilations", "storage")
        filename = f"transcript_{self.meeting_id}.json"
        file_path = os.path.join(compilations_path, filename)

        # Check if file exists
        loop = asyncio.get_event_loop()
        if not await loop.run_in_executor(None, os.path.exists, file_path):
            await self.services.logging_service.error(
                f"Compiled transcript file not found: {file_path}"
            )
            return None

        # Load the file
        async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)

    def _extract_raw_text(self, compiled_transcript: dict) -> str:
        """
        Extract raw text from compiled transcript segments.

        Args:
            compiled_transcript: The compiled transcript data

        Returns:
            Raw text string with all segment content concatenated
        """
        segments = compiled_transcript.get("segments", [])
        return "\n".join([segment["content"] for segment in segments])

    async def _recursive_summarization(
        self, text: str, max_words_per_request: int = 2000
    ) -> tuple[dict[int, list[str]], str]:
        """
        Perform recursive summarization on the text.

        This implementation follows the algorithm from playground/summarize.py:
        1. Split text into chunks of max_words_per_request
        2. Summarize each chunk (200-500 words)
        3. Combine summaries and repeat until under max_words_per_request
        4. Return all summary layers and final summary

        Args:
            text: Raw text to summarize
            max_words_per_request: Maximum words per summarization request

        Returns:
            Tuple of (summary_layers dict, final_summary string)
            summary_layers format: {level: [summary1, summary2, ...]}
        """
        import os

        from source.services.summarization_job_manager.prompts import (
            LEVEL_0_SYSTEM_MESSAGE,
            LEVEL_0_USER_CONTENT_TEMPLATE,
            LEVEL_N_SYSTEM_MESSAGE,
            LEVEL_N_USER_CONTENT_TEMPLATE,
        )

        # Get Ollama configuration
        OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")

        summary_layers: dict[int, list[str]] = {}
        level = 0
        current_text = text

        await self.services.logging_service.info(
            f"Starting recursive summarization with Ollama model: {OLLAMA_MODEL}"
        )

        while True:
            word_count = len(current_text.split())
            await self.services.logging_service.info(
                f"Summarization level {level}: {word_count} words"
            )

            # Base case: already under max_words_per_request words
            if word_count <= max_words_per_request and level > 0:
                await self.services.logging_service.info(
                    f"✅ Under {max_words_per_request} words! Done."
                )
                final_summary = current_text
                break

            # Split into max_words_per_request word chunks
            words = current_text.split()
            chunks = []
            for i in range(0, len(words), max_words_per_request):
                chunk = " ".join(words[i : i + max_words_per_request])
                chunks.append(chunk)

            await self.services.logging_service.info(f"Split into {len(chunks)} chunks")

            # Summarize each chunk
            level_summaries = []
            for i, chunk in enumerate(chunks):
                await self.services.logging_service.info(
                    f"Summarizing chunk {i+1}/{len(chunks)} ({len(chunk.split())} words)..."
                )

                # Choose system message and user content based on level
                if level == 0:
                    system_message = LEVEL_0_SYSTEM_MESSAGE
                    user_content = LEVEL_0_USER_CONTENT_TEMPLATE.format(
                        chunk_number=i + 1,
                        total_chunks=len(chunks),
                        chunk_text=chunk,
                    )
                else:
                    system_message = LEVEL_N_SYSTEM_MESSAGE
                    user_content = LEVEL_N_USER_CONTENT_TEMPLATE.format(
                        chunk_number=i + 1,
                        total_chunks=len(chunks),
                        chunk_text=chunk,
                    )

                # Call Ollama via OllamaRequestManager
                try:
                    result = await self.services.ollama_request_manager.query(
                        model=OLLAMA_MODEL,
                        messages=[
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": user_content},
                        ],
                        keep_alive=10,  # Keep model in memory for 10 seconds
                        timeout_ms=120000,  # 2 minutes timeout
                    )

                    summary = result.content

                    await self.services.logging_service.info(
                        f"Generated summary: {len(summary.split())} words"
                    )
                    level_summaries.append(summary)

                except Exception as e:
                    await self.services.logging_service.error(
                        f"Failed to summarize chunk {i+1}: {str(e)}"
                    )
                    # Continue with other chunks
                    continue

            # Store this level's summaries
            summary_layers[level] = level_summaries

            # Combine summaries for next iteration
            current_text = "\n\n".join(level_summaries)
            level += 1

        await self.services.logging_service.info(
            f"Recursive summarization completed with {len(summary_layers)} levels"
        )

        return summary_layers, final_summary

    async def _update_transcription_files(
        self, summary_layers: dict[int, list[str]], final_summary: str
    ) -> None:
        """
        Update all individual transcription files with summaries.

        Args:
            summary_layers: Dictionary of summary layers {level: [summaries]}
            final_summary: The final consolidated summary
        """
        import asyncio
        import json
        import os

        import aiofiles
        from sqlalchemy import select

        from source.server.sql_models import UserTranscriptsModel

        await self.services.logging_service.info(
            f"Updating {len(self.transcript_ids)} transcription files with summaries"
        )

        for transcript_id in self.transcript_ids:
            try:
                # Get transcript metadata from SQL
                stmt = select(UserTranscriptsModel).where(UserTranscriptsModel.id == transcript_id)
                result = await self.services.server.sql_client.execute(stmt)

                if not result:
                    await self.services.logging_service.warning(
                        f"Transcription {transcript_id} not found in SQL, skipping..."
                    )
                    continue

                transcript_model = result[0]
                filename = transcript_model["transcript_filename"]
                storage_path = self.services.transcription_file_service_manager.get_storage_path()
                file_path = os.path.join(storage_path, filename)

                # Load existing transcription data
                loop = asyncio.get_event_loop()
                if not await loop.run_in_executor(None, os.path.exists, file_path):
                    await self.services.logging_service.warning(
                        f"Transcription file not found: {file_path}, skipping..."
                    )
                    continue

                async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
                    content = await f.read()
                    transcription_data = json.loads(content)

                # Update with summaries
                transcription_data["summary_layers"] = summary_layers
                transcription_data["summary"] = final_summary
                transcription_data["summarized_at"] = get_current_timestamp_est().isoformat()

                # Save updated transcription
                async with aiofiles.open(file_path, mode="w", encoding="utf-8") as f:
                    await f.write(json.dumps(transcription_data, indent=2, ensure_ascii=False))

                await self.services.logging_service.info(
                    f"Updated transcription {transcript_id} with summaries"
                )

            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to update transcription {transcript_id}: {str(e)}"
                )
                # Continue with other transcriptions


class BaseSummarizationJobManagerService(Manager):
    """Base class for summarization job manager service."""

    async def create_and_queue_summarization_job(
        self,
        meeting_id: str,
        compiled_transcript_id: str,
        transcript_ids: list[str],
        user_ids: list[str],
    ) -> str:
        """Create a new summarization job and add it to the queue."""
        pass

    async def get_job_status(self, job_id: str) -> dict:
        """Get the status of a specific job."""
        pass

    async def get_queue_statistics(self) -> dict:
        """Get statistics about the job queue."""
        pass


class SummarizationJobManagerService(BaseSummarizationJobManagerService):
    """
    Service for managing summarization job queue.

    This service handles the creation and processing of summarization jobs
    when transcription compilation tasks are completed. It uses an event-based
    job queue that processes one job at a time.
    """

    def __init__(self, context: Context):
        """
        Initialize the summarization job manager.

        Args:
            context: Application context
        """
        super().__init__(context)
        self._job_queue: JobQueue[SummarizationJob] | None = None
        self._active_jobs: dict[str, SummarizationJob] = {}

    async def on_start(self, services: ServicesManager) -> None:
        """
        Initialize the summarization job manager.

        Args:
            services: Services manager instance
        """
        await super().on_start(services)

        # Initialize the job queue with callbacks
        self._job_queue = JobQueue[SummarizationJob](
            max_retries=2,  # Retry failed jobs up to 2 times
            on_job_started=self._on_job_started,
            on_job_complete=self._on_job_complete,
            on_job_failed=self._on_job_failed,
        )

        await self.services.logging_service.info("Summarization Job Manager initialized")

    async def on_close(self) -> None:
        """Cleanup when service is shutting down."""
        if self._job_queue and self._job_queue.is_running():
            await self.services.logging_service.info(
                "Shutting down summarization job queue, waiting for current job to complete..."
            )
            await self._job_queue.stop(wait_for_completion=True)

        await super().on_close()

    # -------------------------------------------------------------- #
    # Public API
    # -------------------------------------------------------------- #

    async def create_and_queue_summarization_job(
        self,
        meeting_id: str,
        compiled_transcript_id: str,
        transcript_ids: list[str],
        user_ids: list[str],
    ) -> str:
        """
        Create a new summarization job and add it to the queue.

        This method also creates a corresponding entry in the SQL database
        to track the job's progress.

        Args:
            meeting_id: ID of the meeting to summarize
            compiled_transcript_id: ID of the compiled transcript
            transcript_ids: List of individual transcript IDs to update
            user_ids: List of user IDs who participated in the meeting

        Returns:
            The job ID of the created summarization job
        """
        # Generate unique job ID
        job_id = generate_16_char_uuid()

        # Create the job
        job = SummarizationJob(
            job_id=job_id,
            meeting_id=meeting_id,
            compiled_transcript_id=compiled_transcript_id,
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
            f"Created summarization job {job_id} for meeting {meeting_id}"
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

    async def _create_sql_job_entry(self, job: SummarizationJob) -> None:
        """
        Create a SQL database entry for the summarization job.

        Args:
            job: The summarization job to create an entry for
        """
        if not self.services.sql_recording_service_manager:
            await self.services.logging_service.warning(
                "SQL recording service not available, skipping job entry creation"
            )
            return

        try:
            await self.services.sql_recording_service_manager.create_job_status(
                job_id=job.job_id,
                job_type=JobsType.SUMMARIZING,
                meeting_id=job.meeting_id,
                created_at=job.created_at,
                status=JobsStatus.PENDING,
            )
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to create SQL entry for summarization job {job.job_id}: {e}"
            )

    async def _update_sql_job_status(self, job: SummarizationJob) -> None:
        """
        Update the SQL database entry for the summarization job.

        Args:
            job: The summarization job to update
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
                f"Failed to update SQL entry for summarization job {job.job_id}: {e}"
            )

    # -------------------------------------------------------------- #
    # Job Queue Callbacks
    # -------------------------------------------------------------- #

    async def _on_job_started(self, job: SummarizationJob) -> None:
        """
        Callback when a job starts processing.

        Args:
            job: The job that started
        """
        await self.services.logging_service.info(
            f"Started summarization job {job.job_id} for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

    async def _on_job_complete(self, job: SummarizationJob) -> None:
        """
        Callback when a job completes successfully.

        Args:
            job: The job that completed
        """
        await self.services.logging_service.info(
            f"Completed summarization job {job.job_id} for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

        # Send DM notifications to all users who participated in the meeting
        await self._send_meeting_complete_notifications(job)

    async def _send_meeting_complete_notifications(self, job: SummarizationJob) -> None:
        """
        Send DM notifications to all users who participated in the meeting.

        Args:
            job: The completed summarization job
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
                            "**✅ Your recording has been transcribed, compiled, and summarized!**\n\n"
                            "The meeting transcription and AI-generated summary are now available."
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
                            f"Sent completion notification to user {user_id} for meeting {job.meeting_id}"
                        )
                    else:
                        await self.services.logging_service.warning(
                            f"Failed to send completion notification to user {user_id}"
                        )

                except Exception as e:
                    await self.services.logging_service.error(
                        f"Error sending notification to user {user_id}: {e}"
                    )

        except Exception as e:
            await self.services.logging_service.error(
                f"Error in _send_meeting_complete_notifications: {e}"
            )

    async def _on_job_failed(self, job: SummarizationJob) -> None:
        """
        Callback when a job fails.

        Args:
            job: The job that failed
        """
        await self.services.logging_service.error(
            f"Failed summarization job {job.job_id} for meeting {job.meeting_id}: "
            f"{job.error_message}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

        # Optionally: Send notification to admin or user about failed summarization
