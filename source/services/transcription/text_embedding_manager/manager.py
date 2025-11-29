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
from source.services.transcription.text_embedding_manager.summary_partitioner import (
    partition_multi_level_summaries,
)
from source.services.transcription.text_embedding_manager.text_partitioner import (
    partition_transcript_segments,
)
from source.utils import generate_16_char_uuid

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
        4. Store embeddings in ChromaDB (embeddings collection)
        5. Process summaries if available
        6. Generate summary embeddings with GPU lock
        7. Store summary embeddings in ChromaDB (summaries collection)
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

            # Step 4: Store embeddings in ChromaDB (embeddings collection)
            await self._store_embeddings(partitions, embeddings)

            await self.services.logging_service.info(
                f"Successfully stored embeddings for meeting {self.meeting_id}"
            )

            # Step 5: Process summaries if available
            if "summary_layers" in compiled_transcript and "summary" in compiled_transcript:
                await self.services.logging_service.info(
                    f"Processing summaries for meeting {self.meeting_id}"
                )

                summary_partitions = await self._partition_summaries(compiled_transcript)

                if summary_partitions:
                    await self.services.logging_service.info(
                        f"Created {len(summary_partitions)} summary partitions for embedding"
                    )

                    # Step 6: Generate summary embeddings with GPU lock
                    summary_embeddings = await self._generate_embeddings(summary_partitions)

                    await self.services.logging_service.info(
                        f"Generated {len(summary_embeddings)} summary embeddings"
                    )

                    # Step 7: Store summary embeddings in ChromaDB (summaries collection)
                    await self._store_summary_embeddings(summary_partitions, summary_embeddings)

                    await self.services.logging_service.info(
                        "Successfully stored summary embeddings in summaries collection"
                    )
                else:
                    await self.services.logging_service.warning(
                        f"No summary partitions created for meeting {self.meeting_id}"
                    )
            else:
                await self.services.logging_service.info(
                    f"No summaries found in compiled transcript for meeting {self.meeting_id}"
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
            async with aiofiles.open(file_path, encoding="utf-8") as f:
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

        Handles both transcript partitions (with 'contextualized_text') and
        summary partitions (with 'text').

        Args:
            partitions: List of partition dicts with either 'contextualized_text' or 'text' field

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

                # Extract text from partitions
                # Handle both transcript format (contextualized_text) and summary format (text)
                texts = []
                for p in partitions:
                    if "contextualized_text" in p:
                        texts.append(p["contextualized_text"])
                    elif "text" in p:
                        texts.append(p["text"])
                    else:
                        raise ValueError(f"Partition missing text field: {p.keys()}")

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

    async def _partition_summaries(
        self, compiled_transcript: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Partition summary layers and final summary for embedding.

        Args:
            compiled_transcript: The compiled transcript with summary_layers and summary

        Returns:
            List of summary partitions ready for embedding
        """
        summary_layers = compiled_transcript.get("summary_layers", {})
        final_summary = compiled_transcript.get("summary", "")

        if not summary_layers and not final_summary:
            return []

        # Use the summary partitioner to create partitions with proper metadata
        partitions = partition_multi_level_summaries(
            summary_layers=summary_layers,
            final_summary=final_summary,
            meeting_id=self.meeting_id,
            guild_id=self.guild_id,
            max_tokens=512,
            overlap_percentage=0.15,
            buffer_percentage=0.05,
        )

        return partitions

    async def _store_summary_embeddings(
        self,
        partitions: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        """
        Store summary embeddings in ChromaDB summaries collection.

        Args:
            partitions: List of summary partition dicts
            embeddings: List of embedding vectors
        """
        if len(partitions) != len(embeddings):
            raise ValueError(
                f"Partition count ({len(partitions)}) does not match "
                f"embedding count ({len(embeddings)})"
            )

        # Get ChromaDB client
        vector_db_client = self.services.server.vector_db_client

        # Use the summaries collection for all summary embeddings
        collection_name = "summaries"

        await self.services.logging_service.info(
            f"Storing summary embeddings in collection: {collection_name}"
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
            # Create unique ID based on whether it's a subsummary or final summary
            partition_metadata = partition["metadata"]

            if partition_metadata.get("is_subsummary", False):
                # Subsummary: meeting_id_level{level}_summary{index}_segment{segment_index}
                level = partition_metadata.get("summary_level", 0)
                summary_index = partition_metadata.get("summary_index_in_level", 0)
                segment_index = partition.get("segment_index", 0)
                doc_id = (
                    f"{self.meeting_id}_level{level}_summary{summary_index}_segment{segment_index}"
                )
            else:
                # Final summary: meeting_id_final_segment{segment_index}
                segment_index = partition.get("segment_index", 0)
                doc_id = f"{self.meeting_id}_final_segment{segment_index}"

            # Build metadata for ChromaDB
            metadata = {
                "meeting_id": self.meeting_id,
                "guild_id": self.guild_id,
                "is_subsummary": partition_metadata.get("is_subsummary", False),
                "segment_index": partition.get("segment_index", 0),
                "global_partition_index": partition.get("global_partition_index", 0),
                "estimated_tokens": partition.get("estimated_tokens", 0),
                "start_char": partition.get("start_char", 0),
                "end_char": partition.get("end_char", 0),
            }

            # Add subsummary-specific metadata
            if partition_metadata.get("is_subsummary", False):
                metadata["summary_level"] = partition_metadata.get("summary_level", 0)
                metadata["summary_index_in_level"] = partition_metadata.get(
                    "summary_index_in_level", 0
                )
            else:
                metadata["is_final_summary"] = partition_metadata.get("is_final_summary", False)

            ids.append(doc_id)
            documents.append(partition["text"])
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
            f"Stored {len(ids)} summary embeddings in collection {collection_name}"
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
            on_job_started=self._on_job_started,
            on_job_complete=self._on_job_complete,
            on_job_failed=self._on_job_failed,
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

        # Create SQL entry for the job
        await self._create_sql_job_entry(job)

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
    # Private Methods
    # -------------------------------------------------------------- #

    async def _create_sql_job_entry(self, job: TextEmbeddingJob) -> None:
        """
        Create a SQL database entry for the text embedding job.

        Args:
            job: The text embedding job to create an entry for
        """
        if not self.services.sql_recording_service_manager:
            await self.services.logging_service.warning(
                "SQL recording service not available, skipping job entry creation"
            )
            return

        try:
            await self.services.sql_recording_service_manager.create_job_status(
                job_id=job.job_id,
                job_type=JobsType.TEXT_EMBEDDING,
                meeting_id=job.meeting_id,
                created_at=job.created_at,
                status=JobsStatus.PENDING,
            )
        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to create SQL entry for text embedding job {job.job_id}: {e}"
            )

    async def _update_sql_job_status(self, job: TextEmbeddingJob) -> None:
        """
        Update the SQL database entry for the text embedding job.

        Args:
            job: The text embedding job to update
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
                f"Failed to update SQL entry for text embedding job {job.job_id}: {e}"
            )

    # -------------------------------------------------------------- #
    # Job Callbacks
    # -------------------------------------------------------------- #

    async def _on_job_started(self, job: TextEmbeddingJob) -> None:
        """Called when a job starts processing."""
        await self.services.logging_service.info(
            f"Text embedding job {job.job_id} started for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

    async def _on_job_complete(self, job: TextEmbeddingJob) -> None:
        """Called when a job completes successfully."""
        await self.services.logging_service.info(
            f"Text embedding job {job.job_id} completed for meeting {job.meeting_id}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

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

    async def _on_job_failed(self, job: TextEmbeddingJob) -> None:
        """Called when a job fails."""
        error_msg = job.error_message or "Unknown error"

        await self.services.logging_service.error(
            f"Text embedding job {job.job_id} failed for meeting {job.meeting_id}: {error_msg}"
        )

        # Update SQL status
        await self._update_sql_job_status(job)

        # Send error notification to meeting requestor
        await self._send_embedding_error_dm(job)

    async def _send_embedding_error_dm(self, job: TextEmbeddingJob) -> None:
        """Send error notification to meeting requestor when embedding generation fails."""
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
                title="❌ Embedding Generation Failed",
                description=(
                    f"An error occurred while generating vector embeddings for meeting `{job.meeting_id}`.\n\n"
                    f"**Job ID:** `{job.job_id}`\n"
                    f"**Error:** {job.error_message or 'Unknown error'}\n\n"
                    "The transcript and summaries could not be indexed for semantic search. "
                    "This may be due to ChromaDB issues or embedding model problems."
                ),
                color=discord.Color.red(),
            )

            embed.add_field(
                name="Next Steps",
                value="Run `/process_step` with the meeting ID to retry embedding generation.",
                inline=False,
            )

            # Send DM to requestor only
            from source.utils import BotUtils

            await BotUtils.send_dm(
                self.services.context.bot, requestor_id, embed=embed
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to send embedding error DM for meeting {job.meeting_id}: {e}"
            )
