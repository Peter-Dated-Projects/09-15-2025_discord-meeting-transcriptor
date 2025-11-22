"""
Text Embedding Job Manager Service.

This service manages the generation of text embeddings from compiled meeting transcripts
for use in Retrieval-Augmented Generation (RAG) systems. It handles:
- GPU-aware model loading and offloading
- Segmentation with overlapping context windows
- Batch embedding generation
- ChromaDB storage in per-guild collections
- User DM notifications after completion

Model: BAAI/bge-large-en-v1.5 (sentence-transformers)
GPU Resource: Requires GPU VRAM, uses gpu_resource_manager for coordination
Storage: ChromaDB collections named 'embeddings_{guild_id}'
Integration: Called after summarization job completes, sends DM notifications to users

Usage:
    # Queue an embedding job after summarization
    job_id = await text_embedding_manager.create_and_queue_embedding_job(
        meeting_id="abc123",
        guild_id="guild_456",
        compiled_transcript_id="xyz789",
        user_ids=["user1", "user2"]
    )

    # Check job status
    status = await text_embedding_manager.get_job_status(job_id)
"""

from __future__ import annotations

import asyncio
import gc
import json
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aiofiles

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from source.server.sql_models import JobsStatus, JobsType
from source.services.common.job import Job, JobQueue
from source.services.manager import BaseTextEmbeddingJobManagerService
from source.services.text_embedding_manager.text_partitioner import (
    partition_transcript_segments,
)
from source.utils import generate_16_char_uuid, get_current_timestamp_est

# -------------------------------------------------------------- #
# Embedding Model Handler
# -------------------------------------------------------------- #


class EmbeddingModelHandler:
    """
    Handler for text embedding model with GPU lifecycle management.

    Manages loading, offloading, and inference for the BAAI/bge-large-en-v1.5
    sentence transformer model.

    Note: Load/offload is currently manual per-job, similar to whisper/ollama pattern.
    """

    def __init__(self, model_name: str = "BAAI/bge-large-en-v1.5"):
        """
        Initialize the embedding model handler.

        Args:
            model_name: Name of the sentence-transformers model to use
        """
        self.model_name = model_name
        self.model = None

    def load_model(self) -> None:
        """Load the embedding model onto the GPU."""
        if self.is_loaded():
            return  # Already loaded

        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(self.model_name)

    def offload_model(self) -> None:
        """
        Offload the model from GPU and free memory.

        Moves model to CPU (if applicable), clears reference, and triggers
        garbage collection with CUDA cache clearing.
        """
        if self.model is not None:
            # Try to move to CPU first
            if hasattr(self.model, "to"):
                try:
                    self.model.to("cpu")
                except Exception:
                    pass

            # Drop reference
            self.model = None

        # Encourage memory to be freed
        gc.collect()

        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def is_loaded(self) -> bool:
        """Check if the model is currently loaded."""
        return self.model is not None

    def encode(
        self,
        texts: list[str],
        batch_size: int = 32,
        normalize_embeddings: bool = True,
    ) -> list[list[float]]:
        """
        Encode texts into embeddings.

        Args:
            texts: List of text strings to embed
            batch_size: Batch size for encoding
            normalize_embeddings: Whether to normalize embeddings

        Returns:
            List of embedding vectors (list of floats)

        Raises:
            ValueError: If model is not loaded
        """
        if not self.is_loaded():
            raise ValueError("Model is not loaded. Call load_model() first.")

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=normalize_embeddings,
            show_progress_bar=False,
        )

        return embeddings.tolist()

    async def __aenter__(self):
        """Async context manager entry - load model."""
        self.load_model()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - offload model."""
        self.offload_model()
        return False


# -------------------------------------------------------------- #
# Text Embedding Job
# -------------------------------------------------------------- #


@dataclass
class TextEmbeddingJob(Job):
    """
    A job representing text embedding generation for a compiled transcript.

    This job takes a compiled transcript and generates embeddings for each
    segment with overlapping context, storing them in ChromaDB for RAG retrieval.

    Attributes:
        meeting_id: ID of the meeting to generate embeddings for
        compiled_transcript_id: ID of the compiled transcript
        guild_id: Discord guild ID (for collection naming)
        user_ids: List of user IDs who participated in the meeting (for DM notifications)
        services: Reference to ServicesManager for accessing services
    """

    meeting_id: str = ""
    compiled_transcript_id: str = ""
    guild_id: str = ""
    user_ids: list[str] = field(default_factory=list)
    services: ServicesManager = None  # type: ignore

    # -------------------------------------------------------------- #
    # Job Execution
    # -------------------------------------------------------------- #

    async def execute(self) -> None:
        """
        Execute the text embedding job.

        This will:
        1. Load the compiled transcript
        2. Partition segments with overlapping context
        3. Generate embeddings with GPU lock
        4. Store embeddings in ChromaDB
        """
        if not self.services:
            raise RuntimeError("ServicesManager not provided to TextEmbeddingJob")

        await self.services.logging_service.info(
            f"Starting text embedding generation for meeting {self.meeting_id}"
        )

        try:
            # Step 1: Load compiled transcript
            compiled_transcript = await self._load_compiled_transcript()
            if not compiled_transcript:
                await self.services.logging_service.warning(
                    f"No compiled transcript found for meeting {self.meeting_id}"
                )
                return

            # Step 2: Partition segments with overlapping context
            partitions = partition_transcript_segments(compiled_transcript)

            if not partitions:
                await self.services.logging_service.warning(
                    f"No segments to embed for meeting {self.meeting_id}"
                )
                return

            await self.services.logging_service.info(
                f"Created {len(partitions)} partitions for embedding"
            )

            # Step 3: Generate embeddings with GPU lock
            embeddings = await self._generate_embeddings(partitions)

            await self.services.logging_service.info(
                f"Generated {len(embeddings)} embeddings for meeting {self.meeting_id}"
            )

            # Step 4: Store embeddings in ChromaDB
            await self._store_embeddings(partitions, embeddings)

            await self.services.logging_service.info(
                f"Successfully stored embeddings for meeting {self.meeting_id}"
            )

        except Exception as e:
            error_msg = f"Failed to generate embeddings for meeting {self.meeting_id}: {type(e).__name__}: {str(e)}"
            await self.services.logging_service.error(error_msg)
            raise

    # -------------------------------------------------------------- #
    # Helper Methods
    # -------------------------------------------------------------- #

    async def _load_compiled_transcript(self) -> dict[str, Any] | None:
        """
        Load the compiled transcript from storage.

        Returns:
            Compiled transcript dict or None if not found
        """
        try:
            # Build the expected filename
            filename = f"transcript_{self.meeting_id}.json"

            # Get the compilations storage path
            compilation_storage_path = os.path.join(
                self.services.transcription_file_service_manager.transcription_storage_path,
                "compilations",
                "storage",
            )

            file_path = os.path.join(compilation_storage_path, filename)

            # Check if file exists
            loop = asyncio.get_event_loop()
            if not await loop.run_in_executor(None, os.path.exists, file_path):
                await self.services.logging_service.error(
                    f"Compiled transcript file not found: {file_path}"
                )
                return None

            # Read the JSON file
            async with aiofiles.open(file_path, mode="r", encoding="utf-8") as f:
                content = await f.read()
                compiled_transcript = json.loads(content)

            # Validate structure
            if "segments" not in compiled_transcript:
                await self.services.logging_service.error(
                    f"Compiled transcript missing 'segments' key: {file_path}"
                )
                return None

            return compiled_transcript

        except Exception as e:
            await self.services.logging_service.error(
                f"Error loading compiled transcript: {type(e).__name__}: {str(e)}"
            )
            return None

    async def _generate_embeddings(self, partitions: list[dict[str, Any]]) -> list[list[float]]:
        """
        Generate embeddings for partitions with GPU lock.

        Args:
            partitions: List of partition dicts with 'contextualized_text'

        Returns:
            List of embedding vectors
        """
        embeddings = []

        # Acquire GPU lock for embedding generation
        async with self.services.gpu_resource_manager.acquire_lock(
            job_type="text_embedding",
            job_id=self.job_id,
            metadata={
                "meeting_id": self.meeting_id,
                "guild_id": self.guild_id,
                "partition_count": len(partitions),
            },
        ):
            # GPU is now locked - perform embedding generation
            await self.services.logging_service.info(
                f"Acquired GPU lock for embedding generation (meeting: {self.meeting_id})"
            )

            # Create model handler
            handler = EmbeddingModelHandler()

            try:
                # Load model
                await asyncio.get_event_loop().run_in_executor(None, handler.load_model)

                await self.services.logging_service.info("Embedding model loaded successfully")

                # Extract contextualized texts
                texts = [p["contextualized_text"] for p in partitions]

                # Generate embeddings in batches
                embeddings = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: handler.encode(texts, batch_size=32),
                )

                await self.services.logging_service.info(f"Generated {len(embeddings)} embeddings")

            finally:
                # Always offload model
                await asyncio.get_event_loop().run_in_executor(None, handler.offload_model)

                await self.services.logging_service.info("Embedding model offloaded")

        # GPU lock automatically released here
        return embeddings

    async def _store_embeddings(
        self,
        partitions: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """
        Store embeddings in ChromaDB.

        Args:
            partitions: List of partition dicts
            embeddings: List of embedding vectors
        """
        if len(partitions) != len(embeddings):
            raise ValueError(
                f"Partition count ({len(partitions)}) does not match "
                f"embedding count ({len(embeddings)})"
            )

        # Get ChromaDB client
        vector_db_client = self.services.server.vector_db_client

        # Get or create collection for this guild
        collection_name = f"embeddings_{self.guild_id}"

        await self.services.logging_service.info(
            f"Storing embeddings in collection: {collection_name}"
        )

        # Get collection (ChromaDB operations are synchronous)
        loop = asyncio.get_event_loop()
        collection = await loop.run_in_executor(
            None,
            lambda: vector_db_client.get_or_create_collection(collection_name),
        )

        # Prepare data for batch upsert
        ids = []
        documents = []
        metadatas = []
        embedding_vectors = []

        for i, (partition, embedding) in enumerate(zip(partitions, embeddings)):
            # Create unique ID: meeting_id + segment_index
            segment_index = partition["segment_index"]
            doc_id = f"{self.meeting_id}_{segment_index}"

            # Get original segment data
            original_segment = partition["original_segment"]

            # Extract metadata
            metadata = {
                "meeting_id": self.meeting_id,
                "guild_id": self.guild_id,
                "segment_index": segment_index,
                "original_content": original_segment.get("content", ""),
                "user_id": original_segment.get("speaker", {}).get("user_id", ""),
                "user_transcription_file": original_segment.get("speaker", {}).get(
                    "user_transcription_file", ""
                ),
                "start_time": original_segment.get("timestamp", {}).get("start_time", 0.0),
                "end_time": original_segment.get("timestamp", {}).get("end_time", 0.0),
            }

            ids.append(doc_id)
            documents.append(partition["contextualized_text"])
            metadatas.append(metadata)
            embedding_vectors.append(embedding)

        # Upsert to collection (handles both insert and update)
        await loop.run_in_executor(
            None,
            lambda: collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
                embeddings=embedding_vectors,
            ),
        )

        await self.services.logging_service.info(
            f"Stored {len(ids)} embeddings in collection {collection_name}"
        )


# -------------------------------------------------------------- #
# Text Embedding Job Manager Service
# -------------------------------------------------------------- #


class TextEmbeddingJobManagerService(BaseTextEmbeddingJobManagerService):
    """
    Service for managing text embedding job queue.

    This service handles the queue of text embedding jobs that are created
    when transcription compilation completes. It processes one job at a time
    and tracks status in the SQL database.
    """

    def __init__(self, context: Context):
        """
        Initialize the text embedding job manager.

        Args:
            context: Application context
        """
        super().__init__(context)
        self._job_queue: JobQueue[TextEmbeddingJob] | None = None
        self._jobs: dict[str, TextEmbeddingJob] = {}

    # -------------------------------------------------------------- #
    # Manager Lifecycle
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        """Initialize the job queue."""
        await super().on_start(services)

        # Create job queue with callbacks
        self._job_queue = JobQueue[TextEmbeddingJob](
            on_job_start=self._on_job_start,
            on_job_complete=self._on_job_complete,
            on_job_error=self._on_job_error,
        )

        await self.services.logging_service.info("TextEmbeddingJobManagerService initialized")

        return True

    async def on_close(self):
        """Clean up the job queue."""
        if self._job_queue:
            # Note: JobQueue doesn't have explicit cleanup, but we can clear references
            self._job_queue = None

        await self.services.logging_service.info("TextEmbeddingJobManagerService closed")

        return True

    # -------------------------------------------------------------- #
    # Job Management
    # -------------------------------------------------------------- #

    async def create_and_queue_embedding_job(
        self,
        meeting_id: str,
        guild_id: str,
        compiled_transcript_id: str,
        user_ids: list[str],
    ) -> str:
        """
        Create and queue a text embedding job.

        Args:
            meeting_id: ID of the meeting
            guild_id: Discord guild ID
            compiled_transcript_id: ID of the compiled transcript
            user_ids: List of user IDs who participated in the meeting

        Returns:
            Job ID
        """
        # Generate job ID
        job_id = generate_16_char_uuid()

        # Create job
        job = TextEmbeddingJob(
            job_id=job_id,
            meeting_id=meeting_id,
            compiled_transcript_id=compiled_transcript_id,
            guild_id=guild_id,
            user_ids=user_ids,
            services=self.services,
            metadata={
                "meeting_id": meeting_id,
                "guild_id": guild_id,
                "compiled_transcript_id": compiled_transcript_id,
            },
        )

        # Store job reference
        self._jobs[job_id] = job

        # Log job creation to SQL
        await self.services.sql_logging_service_manager.log_job(
            job_id=job_id,
            meeting_id=meeting_id,
            job_type=JobsType.TEXT_EMBEDDING,
            status=JobsStatus.PENDING,
            details=f"Text embedding job created for meeting {meeting_id}",
            metadata={
                "guild_id": guild_id,
                "compiled_transcript_id": compiled_transcript_id,
            },
        )

        # Add to queue
        await self._job_queue.add_job(job)

        await self.services.logging_service.info(
            f"Queued text embedding job {job_id} for meeting {meeting_id}"
        )

        return job_id

    async def get_job_status(self, job_id: str) -> dict:
        """
        Get the status of a specific job.

        Args:
            job_id: The job ID

        Returns:
            Job status dict
        """
        job = self._jobs.get(job_id)

        if not job:
            return {
                "job_id": job_id,
                "status": "not_found",
                "error": "Job not found",
            }

        return {
            "job_id": job.job_id,
            "meeting_id": job.meeting_id,
            "guild_id": job.guild_id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "error_message": job.error_message,
        }

    async def get_queue_statistics(self) -> dict:
        """
        Get statistics about the job queue.

        Returns:
            Queue statistics dict
        """
        if not self._job_queue:
            return {"error": "Job queue not initialized"}

        stats = self._job_queue.get_statistics()

        return {
            "total_jobs": len(self._jobs),
            "queue_size": stats.get("pending_jobs", 0),
            "active_jobs": stats.get("active_jobs", 0),
            "completed_jobs": stats.get("completed_jobs", 0),
            "failed_jobs": stats.get("failed_jobs", 0),
        }

    # -------------------------------------------------------------- #
    # Job Callbacks
    # -------------------------------------------------------------- #

    async def _on_job_start(self, job: TextEmbeddingJob) -> None:
        """Called when a job starts processing."""
        await self.services.logging_service.info(
            f"Text embedding job {job.job_id} started for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self.services.sql_logging_service_manager.log_job(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            job_type=JobsType.TEXT_EMBEDDING,
            status=JobsStatus.IN_PROGRESS,
            details=f"Text embedding job started for meeting {job.meeting_id}",
        )

    async def _on_job_complete(self, job: TextEmbeddingJob) -> None:
        """Called when a job completes successfully."""
        await self.services.logging_service.info(
            f"Text embedding job {job.job_id} completed for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self.services.sql_logging_service_manager.log_job(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            job_type=JobsType.TEXT_EMBEDDING,
            status=JobsStatus.COMPLETED,
            details=f"Text embedding job completed for meeting {job.meeting_id}",
        )

        # Send DM notifications to all users who participated in the meeting
        await self._send_meeting_complete_notifications(job)

    async def _send_meeting_complete_notifications(self, job: TextEmbeddingJob) -> None:
        """
        Send DM notifications to all users who participated in the meeting.

        Args:
            job: The completed text embedding job
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
                            "**✅ Your recording has been transcribed, compiled, summarized, and indexed!**\n\n"
                            "The meeting transcription, AI-generated summary, and searchable embeddings are now available."
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

    async def _on_job_error(self, job: TextEmbeddingJob, error: Exception) -> None:
        """Called when a job fails."""
        error_msg = f"{type(error).__name__}: {str(error)}"

        await self.services.logging_service.error(
            f"Text embedding job {job.job_id} failed for meeting {job.meeting_id}: {error_msg}"
        )

        # Update SQL status
        await self.services.sql_logging_service_manager.log_job(
            job_id=job.job_id,
            meeting_id=job.meeting_id,
            job_type=JobsType.TEXT_EMBEDDING,
            status=JobsStatus.FAILED,
            details=f"Text embedding job failed: {error_msg}",
        )
