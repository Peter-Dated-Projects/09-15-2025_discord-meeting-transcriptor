"""
Text Partitioner for Transcript Segments.

This module provides functionality to partition compiled transcript segments
with overlapping context windows for embedding generation.
"""

from typing import Any


def partition_transcript_segments(compiled_transcript_data: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Partition transcript segments with overlapping context for embedding.
    
    Creates partitions where each segment includes ±2 surrounding segments
    for better context preservation during embedding generation.
    
    Args:
        compiled_transcript_data: Compiled transcript dictionary containing 'segments' array
        
    Returns:
        List of partitioned segments, each containing:
            - original_segment: The original segment data (all fields preserved)
            - contextualized_text: Text with ±2 segments for context
            - segment_index: Index of the segment in the original array
            
    Example:
        >>> transcript = {
        ...     "segments": [
        ...         {"content": "Hello", "timestamp": {...}, "speaker": {...}},
        ...         {"content": "World", "timestamp": {...}, "speaker": {...}}
        ...     ]
        ... }
        >>> partitions = partition_transcript_segments(transcript)
        >>> len(partitions) == 2
        True
    """
    
    # Validate input
    if not compiled_transcript_data or "segments" not in compiled_transcript_data:
        raise ValueError("compiled_transcript_data must contain 'segments' key")
    
    segments = compiled_transcript_data.get("segments", [])
    
    if not segments:
        return []
    
    partitions = []
    
    for i, segment in enumerate(segments):
        # Calculate window boundaries (±2 segments)
        start_idx = max(0, i - 2)
        end_idx = min(len(segments), i + 3)  # +3 because slice end is exclusive
        
        # Extract context window
        context_segments = segments[start_idx:end_idx]
        
        # Build contextualized text by concatenating content
        contextualized_text = " ".join(
            seg.get("content", "") for seg in context_segments if seg.get("content")
        )
        
        # Create partition entry
        partition = {
            "original_segment": segment,  # Preserve all original data
            "contextualized_text": contextualized_text,
            "segment_index": i,
            "context_window": {
                "start_index": start_idx,
                "end_index": end_idx - 1,  # Adjust to inclusive end
                "window_size": len(context_segments),
            },
        }
        
        partitions.append(partition)
    
    return partitions
