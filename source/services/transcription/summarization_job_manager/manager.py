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

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from source.server.sql_models import JobsStatus, JobsType
from source.services.common.job import Job, JobQueue
from source.services.manager import Manager
from source.utils import generate_16_char_uuid


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
        4. Store summary layers and final summary in the compiled transcript
        5. Update all individual user transcripts with the summaries
        """
        if not self.services:
            raise RuntimeError("ServicesManager not provided to SummarizationJob")

        await self.services.logging_service.info(
            f"Starting summarization for meeting {self.meeting_id}"
        )

        try:
            # Step 1: Retrieve the compiled transcript using transcription_file_manager
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

            # Step 4: Update the compiled transcript file with summaries
            await self._update_compiled_transcript(summary_layers, final_summary)

            # Step 5: Update all individual user transcripts with summaries
            await self._update_individual_transcripts(summary_layers, final_summary)

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
        Load the compiled transcript from storage using transcription_file_manager.

        Returns:
            The compiled transcript data or None if not found
        """
        try:
            compiled_transcript = await self.services.transcription_file_service_manager.retrieve_compiled_transcription(
                self.meeting_id
            )
            return compiled_transcript

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to load compiled transcript for meeting {self.meeting_id}: {str(e)}"
            )
            return None

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

        from source.services.transcription.summarization_job_manager.prompts import (
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

    async def _update_compiled_transcript(
        self, summary_layers: dict[int, list[str]], final_summary: str
    ) -> None:
        """
        Update the compiled transcript file with summaries using transcription_file_manager.

        Args:
            summary_layers: Dictionary of summary layers {level: [summaries]}
            final_summary: The final consolidated summary
        """
        await self.services.logging_service.info(
            f"Updating compiled transcript for meeting {self.meeting_id} with summaries"
        )

        try:
            # Use transcription_file_manager to update compiled transcript
            success = await self.services.transcription_file_service_manager.update_compiled_transcription_with_summary(
                meeting_id=self.meeting_id,
                summary=final_summary,
                summary_layers=summary_layers,
            )

            if not success:
                raise RuntimeError("Failed to update compiled transcript")

            await self.services.logging_service.info(
                f"Successfully updated compiled transcript for meeting {self.meeting_id}"
            )

            # Get the file path for SQL update
            filename = f"transcript_{self.meeting_id}.json"
            compilations_storage_path = (
                self.services.transcription_file_service_manager.compilations_storage_path
            )
            file_path = os.path.join(compilations_storage_path, filename)

            # Update meeting's transcript_ids field with meeting_summary path
            if self.services.sql_recording_service_manager:
                try:
                    # Get current meeting data to preserve user transcript mappings
                    meeting_data = await self.services.sql_recording_service_manager.get_meeting(
                        self.meeting_id
                    )

                    if meeting_data and meeting_data.get("transcript_ids"):
                        transcript_ids_data = meeting_data["transcript_ids"]

                        # Extract user mappings from current data
                        users_array = transcript_ids_data.get("users", [])
                        user_transcript_mapping = {}
                        for user_entry in users_array:
                            user_transcript_mapping.update(user_entry)

                        # Update with meeting_summary path
                        await self.services.sql_recording_service_manager.update_meeting_transcript_ids(
                            meeting_id=self.meeting_id,
                            user_transcript_mapping=user_transcript_mapping,
                            meeting_summary_path=file_path,
                        )

                        await self.services.logging_service.info(
                            f"Updated meeting {self.meeting_id} with meeting_summary path"
                        )
                except Exception as e:
                    await self.services.logging_service.error(
                        f"Failed to update meeting {self.meeting_id} with meeting_summary path: {e}"
                    )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update compiled transcript for meeting {self.meeting_id}: {str(e)}"
            )
            raise

    async def _update_individual_transcripts(
        self, summary_layers: dict[int, list[str]], final_summary: str
    ) -> None:
        """
        Update all individual user transcripts with summary data.

        This method uses transcription_file_manager's bulk update functionality
        to add summary and summary_layers to each user's transcript.

        Args:
            summary_layers: Dictionary of summary layers {level: [summaries]}
            final_summary: The final consolidated summary
        """
        await self.services.logging_service.info(
            f"Updating {len(self.transcript_ids)} individual transcripts with summary data"
        )

        try:
            # Use transcription_file_manager's bulk update method
            results = await self.services.transcription_file_service_manager.bulk_update_transcriptions_with_summary(
                transcript_ids=self.transcript_ids,
                summary=final_summary,
                summary_layers=summary_layers,
            )

            # Log results
            success_count = sum(1 for success in results.values() if success)
            failure_count = len(results) - success_count

            if failure_count > 0:
                failed_ids = [tid for tid, success in results.items() if not success]
                await self.services.logging_service.warning(
                    f"Failed to update {failure_count} transcripts: {failed_ids}"
                )

            await self.services.logging_service.info(
                f"Updated {success_count}/{len(self.transcript_ids)} individual transcripts"
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to update individual transcripts for meeting {self.meeting_id}: {str(e)}"
            )
            raise


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

        # Trigger text embedding job if text_embedding_job_manager is available
        if self.services.text_embedding_job_manager:
            try:
                # Get meeting data to retrieve guild_id
                meeting_data = await self.services.sql_recording_service_manager.get_meeting(
                    meeting_id=job.meeting_id
                )

                if not meeting_data:
                    await self.services.logging_service.warning(
                        f"Could not find meeting data for {job.meeting_id}, skipping text embedding job"
                    )
                    return

                guild_id = meeting_data.get("guild_id")
                if not guild_id:
                    await self.services.logging_service.warning(
                        f"No guild_id found for meeting {job.meeting_id}, skipping text embedding job"
                    )
                    return

                # Create and queue text embedding job
                await self.services.text_embedding_job_manager.create_and_queue_embedding_job(
                    meeting_id=job.meeting_id,
                    guild_id=str(guild_id),
                    compiled_transcript_id=job.compiled_transcript_id,
                    user_ids=job.user_ids,
                )

                await self.services.logging_service.info(
                    f"Queued text embedding job for meeting {job.meeting_id}"
                )

            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to create text embedding job for meeting {job.meeting_id}: {e}"
                )
        else:
            await self.services.logging_service.warning(
                "Text embedding job manager not available, skipping text embedding job"
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

        # Send error notification to meeting requestor
        await self._send_summarization_error_dm(job)

    async def _send_summarization_error_dm(self, job: SummarizationJob) -> None:
        """Send error notification to meeting requestor when summarization fails."""
        try:
            # Get meeting data to retrieve requestor
            meeting_data = await self.services.sql_recording_service_manager.get_meeting(
                meeting_id=job.meeting_id
            )
            if not meeting_data:
                return

            requestor_id = meeting_data.get("requested_by")
            if not requestor_id:
                return

            # Create error embed
            import discord

            embed = discord.Embed(
                title="❌ Summarization Failed",
                description=(
                    f"An error occurred while generating AI summaries for meeting `{job.meeting_id}`.\n\n"
                    f"**Job ID:** `{job.job_id}`\n"
                    f"**Error:** {job.error_message or 'Unknown error'}\n\n"
                    "The compiled transcript could not be summarized using the LLM. "
                    "This may be due to Ollama service issues or transcript format problems."
                ),
                color=discord.Color.red(),
            )

            embed.add_field(
                name="Next Steps",
                value="Run `/process_step` with the meeting ID to retry summarization.",
                inline=False,
            )

            # Send DM to requestor only
            from source.utils import BotUtils

            await BotUtils.send_dm(
                self.services.context.bot, requestor_id, embed=embed
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to send summarization error DM for meeting {job.meeting_id}: {e}"
            )
