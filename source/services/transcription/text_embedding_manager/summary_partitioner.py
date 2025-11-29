"""
Summary Text Partitioner for Text Embedding.

This module provides functionality to partition summary text with overlapping
context windows for embedding generation. Designed for pure text (paragraph format)
that needs to be split based on token limits rather than pre-existing segments.

Key Features:
- Token-based segmentation (max 512 tokens per segment)
- 5% safety buffer to prevent overflow
- Overlapping segments to preserve context and sentiment
- Support for multi-level summaries (subsummaries)
"""

from typing import Any


def estimate_token_count(text: str) -> int:
    """
    Estimate the number of tokens in a text string.

    Uses a simple heuristic: ~1.3 words per token on average for English text.
    This is a conservative estimate that works well for the BAAI/bge-large-en-v1.5 model.

    Args:
        text: Input text string

    Returns:
        Estimated token count
    """
    words = text.split()
    # Conservative estimate: 1.3 words per token
    return int(len(words) / 1.3)


def partition_summary_text(
    summary_text: str,
    max_tokens: int = 512,
    overlap_percentage: float = 0.15,
    buffer_percentage: float = 0.05,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Partition summary text into overlapping segments based on token limits.

    This function splits pure text (paragraphs) into segments that fit within
    the model's token limit while maintaining context through overlapping windows.

    Args:
        summary_text: The summary text to partition (can be multi-paragraph)
        max_tokens: Maximum tokens per segment (default: 512 for BAAI/bge-large-en-v1.5)
        overlap_percentage: Percentage of overlap between segments (default: 0.15 = 15%)
        buffer_percentage: Safety buffer to prevent overflow (default: 0.05 = 5%)
        metadata: Optional metadata to include in each partition (e.g., summary_level, meeting_id)

    Returns:
        List of partitioned segments, each containing:
            - text: The segment text with overlap
            - segment_index: Index of the segment
            - start_char: Starting character position in original text
            - end_char: Ending character position in original text
            - estimated_tokens: Estimated token count
            - metadata: Original metadata plus is_subsummary and summary_level if provided

    Example:
        >>> text = "This is a long summary text..." * 100
        >>> partitions = partition_summary_text(
        ...     text,
        ...     metadata={"summary_level": 2, "meeting_id": "abc123"}
        ... )
        >>> len(partitions) > 1
        True
        >>> partitions[0]["metadata"]["is_subsummary"]
        True
        >>> partitions[0]["metadata"]["summary_level"]
        2
    """
    if not summary_text or not summary_text.strip():
        return []

    # Initialize metadata if not provided
    if metadata is None:
        metadata = {}

    # Calculate effective max tokens with buffer
    effective_max_tokens = int(max_tokens * (1 - buffer_percentage))

    # Calculate overlap size in tokens
    overlap_tokens = int(effective_max_tokens * overlap_percentage)

    # Estimate total tokens in summary
    total_tokens = estimate_token_count(summary_text)

    # If text fits in one segment, return as single partition
    if total_tokens <= effective_max_tokens:
        partition_metadata = metadata.copy()
        partition_metadata["is_subsummary"] = "summary_level" in metadata
        return [
            {
                "text": summary_text,
                "segment_index": 0,
                "start_char": 0,
                "end_char": len(summary_text),
                "estimated_tokens": total_tokens,
                "metadata": partition_metadata,
            }
        ]

    # Split text into sentences for better segmentation boundaries
    sentences = _split_into_sentences(summary_text)

    partitions = []
    current_segment_sentences = []
    current_tokens = 0
    segment_index = 0
    start_char = 0

    # Track sentences for overlap
    overlap_sentences = []
    overlap_token_count = 0

    for i, sentence in enumerate(sentences):
        sentence_tokens = estimate_token_count(sentence)

        # Check if adding this sentence would exceed limit
        if current_tokens + sentence_tokens > effective_max_tokens and current_segment_sentences:
            # Create partition from current segment
            segment_text = " ".join(current_segment_sentences)
            end_char = start_char + len(segment_text)

            partition_metadata = metadata.copy()
            partition_metadata["is_subsummary"] = "summary_level" in metadata

            partitions.append(
                {
                    "text": segment_text,
                    "segment_index": segment_index,
                    "start_char": start_char,
                    "end_char": end_char,
                    "estimated_tokens": current_tokens,
                    "metadata": partition_metadata,
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
            start_char = end_char - len(" ".join(overlap_sentences))
            segment_index += 1
        else:
            # Add sentence to current segment
            current_segment_sentences.append(sentence)
            current_tokens += sentence_tokens

    # Add final segment if there are remaining sentences
    if current_segment_sentences:
        segment_text = " ".join(current_segment_sentences)
        end_char = start_char + len(segment_text)

        partition_metadata = metadata.copy()
        partition_metadata["is_subsummary"] = "summary_level" in metadata

        partitions.append(
            {
                "text": segment_text,
                "segment_index": segment_index,
                "start_char": start_char,
                "end_char": end_char,
                "estimated_tokens": current_tokens,
                "metadata": partition_metadata,
            }
        )

    return partitions


def _split_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences for better segmentation boundaries.

    Uses common sentence terminators while handling edge cases like
    abbreviations and decimal numbers.

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


def partition_multi_level_summaries(
    summary_layers: dict[int, list[str]],
    final_summary: str,
    meeting_id: str,
    guild_id: str,
    max_tokens: int = 512,
    overlap_percentage: float = 0.15,
    buffer_percentage: float = 0.05,
) -> list[dict[str, Any]]:
    """
    Partition multi-level summaries (subsummaries) for embedding.

    This function processes all summary layers and the final summary,
    creating partitions with appropriate metadata to distinguish between
    subsummaries and final summaries.

    Args:
        summary_layers: Dictionary mapping level to list of summary texts
                       Format: {level: [summary1, summary2, ...]}
        final_summary: The final top-level summary text
        meeting_id: Meeting ID for metadata
        guild_id: Guild ID for metadata
        max_tokens: Maximum tokens per segment (default: 512)
        overlap_percentage: Percentage of overlap between segments
        buffer_percentage: Safety buffer percentage

    Returns:
        List of all partitions from all layers, each with appropriate metadata
        indicating whether it's a subsummary and what level it belongs to

    Example:
        >>> layers = {
        ...     0: ["Layer 0 summary 1", "Layer 0 summary 2"],
        ...     1: ["Layer 1 summary 1"]
        ... }
        >>> final = "Final summary"
        >>> partitions = partition_multi_level_summaries(
        ...     layers, final, "meeting_123", "guild_456"
        ... )
        >>> # Subsummaries have is_subsummary=True and summary_level
        >>> # Final summary has is_subsummary=False
    """
    all_partitions = []
    partition_global_index = 0

    # Process each summary layer (subsummaries)
    for level, summaries in sorted(summary_layers.items()):
        for summary_index, summary_text in enumerate(summaries):
            metadata = {
                "meeting_id": meeting_id,
                "guild_id": guild_id,
                "summary_level": level,
                "summary_index_in_level": summary_index,
            }

            partitions = partition_summary_text(
                summary_text=summary_text,
                max_tokens=max_tokens,
                overlap_percentage=overlap_percentage,
                buffer_percentage=buffer_percentage,
                metadata=metadata,
            )

            # Update global indices
            for partition in partitions:
                partition["global_partition_index"] = partition_global_index
                partition_global_index += 1
                all_partitions.append(partition)

    # Process final summary (not a subsummary)
    final_metadata = {
        "meeting_id": meeting_id,
        "guild_id": guild_id,
        "is_final_summary": True,
    }

    final_partitions = partition_summary_text(
        summary_text=final_summary,
        max_tokens=max_tokens,
        overlap_percentage=overlap_percentage,
        buffer_percentage=buffer_percentage,
        metadata=final_metadata,
    )

    # Mark final summary partitions (override is_subsummary to False)
    for partition in final_partitions:
        partition["metadata"]["is_subsummary"] = False
        partition["global_partition_index"] = partition_global_index
        partition_global_index += 1
        all_partitions.append(partition)

    return all_partitions
