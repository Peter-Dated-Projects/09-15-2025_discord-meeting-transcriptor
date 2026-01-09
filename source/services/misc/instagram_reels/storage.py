"""
Instagram Reels VectorDB Storage Module.

This module handles the storage of Instagram Reel summaries in ChromaDB
for retrieval-augmented generation (RAG) in chatbot interactions.

Storage Strategy:
- Collection per guild: `reels_{guild_id}`
- Segments: 500-1000 tokens with 15% overlap
- Metadata: guild_id, reel_url, message_id, message_content, user_id, timestamp, channel_id
- Embedding Model: BAAI/bge-large-en-v1.5 (same as transcript embeddings)
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from source.services.manager import ServicesManager

logger = logging.getLogger(__name__)


async def check_reel_exists(
    services: "ServicesManager",
    reel_url: str,
    guild_id: str,
) -> bool:
    """
    Check if a reel URL already exists in the database.

    Args:
        services: ServicesManager instance for accessing resources
        reel_url: URL of the Instagram reel to check
        guild_id: Discord guild ID

    Returns:
        True if the reel exists, False otherwise
    """
    try:
        vector_db_client = services.server.vector_db_client
        collection_name = f"reels_{guild_id}"

        # Check if collection exists
        collection_exists = await asyncio.get_event_loop().run_in_executor(
            None, lambda: vector_db_client.collection_exists(collection_name)
        )

        if not collection_exists:
            # No collection means no reels stored yet
            return False

        # Get collection
        collection = await asyncio.get_event_loop().run_in_executor(
            None, lambda: vector_db_client.get_or_create_collection(collection_name)
        )

        # Query for documents with this reel_url
        # We use get() instead of query() to filter by metadata
        results = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: collection.get(
                where={"reel_url": reel_url},
                limit=1,  # We only need to know if at least one exists
            ),
        )

        # If we got any results, the reel exists
        exists = results and results.get("ids") and len(results["ids"]) > 0

        if exists:
            await services.logging_service.info(
                f"[Reel Storage] Reel already exists in database: {reel_url}"
            )

        return exists

    except Exception as e:
        await services.logging_service.error(
            f"[Reel Storage] Error checking if reel exists: {e}", exc_info=True
        )
        # On error, assume it doesn't exist to allow processing
        return False


def estimate_token_count(text: str) -> int:
    """
    Estimate the number of tokens in a text string.

    Uses a simple heuristic: ~1.3 words per token on average for English text.

    Args:
        text: Input text string

    Returns:
        Estimated token count
    """
    words = text.split()
    return int(len(words) / 1.3)


def _split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences for better segmentation boundaries.

    Args:
        text: Input text to split

    Returns:
        List of sentences
    """
    import re

    # Replace common abbreviations to avoid false splits
    text = text.replace("Mr.", "Mr")
    text = text.replace("Mrs.", "Mrs")
    text = text.replace("Ms.", "Ms")
    text = text.replace("Dr.", "Dr")
    text = text.replace("Jr.", "Jr")
    text = text.replace("Sr.", "Sr")
    text = text.replace("vs.", "vs")
    text = text.replace("etc.", "etc")
    text = text.replace("e.g.", "eg")
    text = text.replace("i.e.", "ie")

    # Split on sentence terminators followed by space and capital letter or end of string
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z]|$)", text)

    # Filter out empty sentences and strip whitespace
    sentences = [s.strip() for s in sentences if s.strip()]

    return sentences


def partition_reel_summary(
    summary_text: str,
    reel_url: str,
    guild_id: str,
    message_id: str,
    message_content: str,
    user_id: str,
    channel_id: str,
    timestamp: str,
    max_tokens: int = 768,
    overlap_percentage: float = 0.15,
    buffer_percentage: float = 0.05,
) -> list[dict[str, Any]]:
    """
    Partition reel summary into segments for embedding storage.

    Creates overlapping segments of 500-1000 tokens (configurable) to ensure
    proper context preservation for semantic search.

    Args:
        summary_text: The reel summary text to partition
        reel_url: URL of the Instagram reel
        guild_id: Discord guild ID where the reel was posted
        message_id: Discord message ID
        message_content: Original message content
        user_id: Discord user ID who posted the reel
        channel_id: Discord channel ID where the reel was posted
        timestamp: ISO format timestamp of when the reel was posted
        max_tokens: Maximum tokens per segment (default: 768, range 500-1000)
        overlap_percentage: Percentage of overlap between segments (default: 0.15)
        buffer_percentage: Safety buffer to prevent overflow (default: 0.05)

    Returns:
        List of partitions ready for embedding, each containing:
            - text: The segment text
            - segment_index: Index of this segment
            - metadata: All context needed for retrieval
    """
    if not summary_text or not summary_text.strip():
        return []

    # Validate max_tokens is in acceptable range
    if max_tokens < 500 or max_tokens > 1000:
        logger.warning(
            f"max_tokens {max_tokens} outside recommended range (500-1000), " f"adjusting to 768"
        )
        max_tokens = 768

    # Calculate effective max tokens with buffer
    effective_max_tokens = int(max_tokens * (1 - buffer_percentage))

    # Calculate overlap size in tokens
    overlap_tokens = int(effective_max_tokens * overlap_percentage)

    # Estimate total tokens in summary
    total_tokens = estimate_token_count(summary_text)

    # Base metadata for all partitions
    base_metadata = {
        "reel_url": reel_url,
        "guild_id": guild_id,
        "message_id": message_id,
        "message_content": message_content,
        "user_id": user_id,
        "channel_id": channel_id,
        "timestamp": timestamp,
    }

    # If text fits in one segment, return as single partition
    if total_tokens <= effective_max_tokens:
        return [
            {
                "text": summary_text,
                "segment_index": 0,
                "metadata": base_metadata,
            }
        ]

    # Split text into sentences for better segmentation boundaries
    sentences = _split_into_sentences(summary_text)

    partitions = []
    current_segment_sentences = []
    current_tokens = 0
    segment_index = 0

    for sentence in sentences:
        sentence_tokens = estimate_token_count(sentence)

        # Check if adding this sentence would exceed limit
        if current_tokens + sentence_tokens > effective_max_tokens and current_segment_sentences:
            # Create partition from current segment
            segment_text = " ".join(current_segment_sentences)

            partitions.append(
                {
                    "text": segment_text,
                    "segment_index": segment_index,
                    "metadata": base_metadata.copy(),
                }
            )

            # Build overlap buffer from end of current segment
            overlap_sentences = []
            overlap_token_count = 0
            for prev_sentence in reversed(current_segment_sentences):
                prev_tokens = estimate_token_count(prev_sentence)
                if overlap_token_count + prev_tokens <= overlap_tokens:
                    overlap_sentences.insert(0, prev_sentence)
                    overlap_token_count += prev_tokens
                else:
                    break

            # Start new segment with overlap + current sentence
            current_segment_sentences = overlap_sentences + [sentence]
            current_tokens = overlap_token_count + sentence_tokens
            segment_index += 1
        else:
            # Add sentence to current segment
            current_segment_sentences.append(sentence)
            current_tokens += sentence_tokens

    # Add final segment if there are remaining sentences
    if current_segment_sentences:
        segment_text = " ".join(current_segment_sentences)
        partitions.append(
            {
                "text": segment_text,
                "segment_index": segment_index,
                "metadata": base_metadata.copy(),
            }
        )

    return partitions


async def generate_and_store_reel_embeddings(
    services: "ServicesManager",
    summary_text: str,
    reel_url: str,
    guild_id: str,
    message_id: str,
    message_content: str,
    user_id: str,
    channel_id: str,
    timestamp: str | None = None,
) -> None:
    """
    Generate embeddings for reel summary and store in ChromaDB.

    This function:
    1. Partitions the summary into 500-1000 token segments
    2. Generates embeddings with GPU lock
    3. Stores in guild-specific collection: reels_{guild_id}

    Args:
        services: ServicesManager instance for accessing resources
        summary_text: The reel summary to embed and store
        reel_url: URL of the Instagram reel
        guild_id: Discord guild ID
        message_id: Discord message ID
        message_content: Original message content
        user_id: Discord user ID who posted
        channel_id: Discord channel ID where posted
        timestamp: ISO format timestamp (defaults to current time if None)

    Raises:
        Exception: If embedding generation or storage fails
    """
    if timestamp is None:
        timestamp = datetime.utcnow().isoformat()

    await services.logging_service.info(
        f"Starting reel embedding storage for URL: {reel_url} in guild: {guild_id}"
    )

    # Step 1: Partition the summary
    partitions = partition_reel_summary(
        summary_text=summary_text,
        reel_url=reel_url,
        guild_id=guild_id,
        message_id=message_id,
        message_content=message_content,
        user_id=user_id,
        channel_id=channel_id,
        timestamp=timestamp,
        max_tokens=768,  # Good balance for reels (shorter than meeting transcripts)
    )

    if not partitions:
        await services.logging_service.warning(
            f"No partitions created for reel {reel_url}, skipping storage"
        )
        return

    await services.logging_service.info(f"Created {len(partitions)} partition(s) for reel summary")

    # Step 2: Generate embeddings with GPU lock
    embeddings = []

    async with services.gpu_resource_manager.acquire_lock(
        job_type="misc_chat_job", job_id=f"reels-embedding-{message_id}"
    ):
        # Import and use the same embedding handler as transcription service
        from source.services.transcription.text_embedding_manager.manager import (
            EmbeddingModelHandler,
        )

        handler = EmbeddingModelHandler()

        try:
            # Load model (synchronous operation, run in executor)
            await asyncio.get_event_loop().run_in_executor(None, handler.load_model)

            await services.logging_service.info("Embedding model loaded for reel storage")

            # Extract texts from partitions
            texts = [p["text"] for p in partitions]

            # Generate embeddings (synchronous operation, run in executor)
            embeddings = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: handler.encode(texts, batch_size=min(32, len(texts))),
            )

            await services.logging_service.info(
                f"Generated {len(embeddings)} embedding(s) for reel"
            )

        finally:
            # Always offload model
            await asyncio.get_event_loop().run_in_executor(None, handler.offload_model)
            await services.logging_service.info("Embedding model offloaded")

    # Step 3: Store in ChromaDB
    vector_db_client = services.server.vector_db_client
    collection_name = f"reels_{guild_id}"

    await services.logging_service.info(f"Storing embeddings in collection: {collection_name}")

    # Get or create collection (synchronous ChromaDB operation)
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

    for partition, embedding in zip(partitions, embeddings):
        # Create unique ID: message_id + segment_index
        segment_index = partition["segment_index"]
        doc_id = f"{message_id}_{segment_index}"

        ids.append(doc_id)
        documents.append(partition["text"])
        metadatas.append(partition["metadata"])
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

    await services.logging_service.info(
        f"Successfully stored {len(ids)} reel embedding(s) in collection {collection_name}"
    )
