# Summary Embeddings and SQL Model Improvements - Implementation Documentation

**Date:** November 22, 2025  
**Branch:** COMP-21_add-summary-embeddings  
**Status:** ✅ Complete

## Overview

This document describes the implementation of summary embeddings in ChromaDB and improvements to SQL database model validation. The changes enable the system to:
1. Embed meeting summaries at multiple levels (subsummaries)
2. Store summary embeddings in a dedicated ChromaDB collection
3. Enforce proper JSON format validation for SQL database columns
4. Track meeting summaries and transcript mappings in the SQL database

---

## 1. SQL Database Model Validation

### 1.1 Updated Models (`source/server/db_models.py`)

#### ParticipantsMapping (NEW)
Validates the participants field format in the meetings table:
```python
{
    "users": ["user_id_1", "user_id_2", ...]
}
```
- **Validation:** Ensures "users" key exists and contains a list of non-empty string user IDs

#### TranscriptIdsMapping (UPDATED)
Updated to new format with meeting summary path and user transcript mappings:
```python
{
    "meeting_summary": "path/to/summary/file.json",
    "users": [
        {"user_id_1": "transcript_id_1"},
        {"user_id_2": "transcript_id_2"},
        ...
    ]
}
```
- **Validation:** 
  - Ensures "meeting_summary" key exists (string)
  - Ensures "users" key exists (array)
  - Each user entry must be a dict with exactly one key-value pair
  - Both user_id and transcript_id must be non-empty strings

---

## 2. Summary Text Partitioning System

### 2.1 New Module (`source/services/text_embedding_manager/summary_partitioner.py`)

Created a sophisticated text partitioning system for summaries with the following features:

#### Token-Based Segmentation
- **Max tokens per segment:** 512 (matches BAAI/bge-large-en-v1.5 model)
- **Safety buffer:** 5% (prevents overflow)
- **Effective max tokens:** 486 tokens per segment
- **Token estimation:** Conservative heuristic (1.3 words per token)

#### Overlapping Segments
- **Overlap percentage:** 15% (default)
- **Purpose:** Preserve context and sentiment across segment boundaries
- **Implementation:** Each new segment includes sentences from the end of the previous segment

#### Sentence-Aware Splitting
- Splits text on sentence boundaries rather than arbitrary character positions
- Handles common abbreviations (Mr., Dr., etc.)
- Uses regex-based sentence detection with edge case handling

#### Subsummary Level Tracking
Each partition includes metadata indicating:
- `is_subsummary`: Boolean flag (True for subsummaries, False for final summary)
- `summary_level`: Integer indicating the summarization layer (0, 1, 2, ...)
- `summary_index_in_level`: Index within that specific layer
- `global_partition_index`: Unique index across all partitions

### 2.2 Key Functions

#### `partition_summary_text()`
Partitions a single summary text into overlapping segments.

**Parameters:**
- `summary_text`: The text to partition
- `max_tokens`: Maximum tokens per segment (default: 512)
- `overlap_percentage`: Overlap ratio (default: 0.15)
- `buffer_percentage`: Safety buffer (default: 0.05)
- `metadata`: Optional metadata to include

**Returns:**
```python
[
    {
        "text": "segment text with overlap...",
        "segment_index": 0,
        "start_char": 0,
        "end_char": 1234,
        "estimated_tokens": 486,
        "metadata": {
            "is_subsummary": True/False,
            "summary_level": 2,  # if subsummary
            ...
        }
    },
    ...
]
```

#### `partition_multi_level_summaries()`
Processes all summary layers and final summary from a meeting.

**Parameters:**
- `summary_layers`: Dict mapping level to list of summaries `{0: [...], 1: [...]}`
- `final_summary`: The top-level summary text
- `meeting_id`: Meeting ID for metadata
- `guild_id`: Guild ID for metadata
- Additional partitioning parameters

**Returns:**
- Combined list of all partitions from all layers with appropriate metadata

---

## 3. Text Embedding Manager Updates

### 3.1 Enhanced Job Execution (`source/services/text_embedding_manager/manager.py`)

Updated the `TextEmbeddingJob.execute()` method to process both transcript segments AND summaries:

**New Flow:**
1. Load compiled transcript
2. Partition transcript segments (existing)
3. Generate and store transcript embeddings (existing)
4. **NEW:** Check for summaries in compiled transcript
5. **NEW:** Partition multi-level summaries using `summary_partitioner`
6. **NEW:** Generate summary embeddings
7. **NEW:** Store summary embeddings in "summaries" collection

### 3.2 New Helper Methods

#### `_partition_summaries()`
Extracts summary_layers and summary from compiled transcript and calls `partition_multi_level_summaries()`.

#### `_store_summary_embeddings()`
Stores summary embeddings in the dedicated "summaries" ChromaDB collection.

**Document ID Format:**
- **Subsummaries:** `{meeting_id}_level{level}_summary{index}_segment{segment_index}`
- **Final Summary:** `{meeting_id}_final_segment{segment_index}`

**Metadata Stored:**
```python
{
    "meeting_id": "...",
    "guild_id": "...",
    "is_subsummary": True/False,
    "segment_index": 0,
    "global_partition_index": 5,
    "estimated_tokens": 486,
    "start_char": 0,
    "end_char": 1234,
    # If subsummary:
    "summary_level": 2,
    "summary_index_in_level": 0,
    # If final summary:
    "is_final_summary": True
}
```

---

## 4. SQL Database Updates

### 4.1 New Method (`source/services/recording_sql_manager/manager.py`)

#### `update_meeting_transcript_ids()`
Updates the meetings table transcript_ids field with the new format.

**Parameters:**
- `meeting_id`: Meeting ID
- `user_transcript_mapping`: Dict mapping user_id to transcript_id
- `meeting_summary_path`: Optional path to meeting summary file

**SQL Update:**
```python
{
    "meeting_summary": "{path}",
    "users": [{"user_id": "transcript_id"}, ...]
}
```

### 4.2 Integration Points

#### Transcription Job Manager
- **Updated:** `TranscriptionJob` dataclass to track `user_transcript_mapping`
- **When:** Transcripts are saved, mapping is recorded
- **Action:** On job completion, calls `update_meeting_transcript_ids()` with initial data (meeting_summary is empty)

#### Summarization Job Manager
- **When:** Compiled transcript is updated with summaries
- **Action:** Reads current meeting data, preserves user mappings, updates meeting_summary_path
- **File Path:** Points to the compiled transcript file containing summaries

---

## 5. ChromaDB Collections

### 5.1 Embeddings Collection (Existing)
- **Collection Name:** `embeddings_{guild_id}` (per-guild)
- **Purpose:** Store transcript segment embeddings
- **Document Format:** Contextualized transcript segments with ±2 segment overlap

### 5.2 Summaries Collection (NEW)
- **Collection Name:** `summaries` (global, shared across guilds)
- **Purpose:** Store all summary embeddings (subsummaries and final summaries)
- **Document Format:** Summary text segments with 15% overlap
- **Metadata:** Includes is_subsummary flag and level tracking

**Design Decision:** Using a single global "summaries" collection allows:
- Cross-guild summary retrieval if needed
- Simplified management
- Clear separation between transcript and summary embeddings
- Can be filtered by guild_id in queries

---

## 6. Workflow Changes

### Before Changes
```
Recording → Transcription → Compilation → Summarization → [Embeddings only for transcripts]
```

### After Changes
```
Recording → Transcription → Compilation → Summarization → Embeddings (Transcripts + Summaries)
                                                                      ↓                    ↓
                                                           embeddings_{guild_id}     summaries
```

### Detailed Flow

1. **Transcription Job Completes:**
   - Saves transcripts to file
   - Creates SQL entries
   - **Tracks user_id → transcript_id mapping**
   - **Updates meeting.transcript_ids with initial format** (meeting_summary empty)
   - Triggers compilation job

2. **Compilation Job Completes:**
   - Creates compiled transcript file
   - Triggers summarization job

3. **Summarization Job Completes:**
   - Adds summary_layers and summary to compiled transcript
   - **Updates meeting.transcript_ids with meeting_summary path**
   - Triggers text embedding job

4. **Text Embedding Job:**
   - Processes transcript segments → embeddings_{guild_id}
   - **NEW: Processes summary layers + final summary → summaries**
   - Both use same embedding model (BAAI/bge-large-en-v1.5)

---

## 7. Testing Considerations

### Test Scenarios

1. **Validation Testing:**
   - Test ParticipantsMapping with valid/invalid formats
   - Test TranscriptIdsMapping with new format
   - Test empty meeting_summary path handling

2. **Partitioning Testing:**
   - Test summary text under 512 tokens (single partition)
   - Test summary text over 512 tokens (multiple partitions)
   - Test overlap calculation and sentence boundary detection
   - Test multi-level summary partitioning

3. **Embedding Generation:**
   - Test subsummary embeddings have correct metadata
   - Test final summary embeddings have is_subsummary=False
   - Test all embeddings stored in "summaries" collection
   - Test document ID format

4. **SQL Updates:**
   - Test transcript_ids format after transcription
   - Test meeting_summary path update after summarization
   - Test data preservation across updates

---

## 8. Migration Notes

### For Existing Meetings

Existing meetings may have transcript_ids in the old format:
```python
# Old format
{"user_id_1": "transcript_id_1", "user_id_2": "transcript_id_2"}
```

A migration script may be needed to convert to new format:
```python
# New format
{
    "meeting_summary": "",
    "users": [
        {"user_id_1": "transcript_id_1"},
        {"user_id_2": "transcript_id_2"}
    ]
}
```

### Backward Compatibility

- The validation models will reject old format data
- Consider adding a migration script in `scripts/backpropagate/`
- May need to re-process meetings to populate meeting_summary paths

---

## 9. Configuration

No new configuration required. The system uses existing settings:
- Embedding model: BAAI/bge-large-en-v1.5
- ChromaDB client: Existing server.vector_db_client
- Token limits: Hardcoded (512 tokens, 5% buffer, 15% overlap)

---

## 10. Performance Considerations

### Token Estimation
- Uses conservative heuristic (1.3 words per token)
- May occasionally underestimate tokens for technical content
- 5% buffer provides safety margin

### Embedding Generation
- Summary embeddings processed in same GPU lock as transcript embeddings
- No additional GPU memory overhead
- Batch processing (batch_size=32) maintains efficiency

### Storage
- Summary embeddings typically much smaller than transcript embeddings
- Single "summaries" collection simplifies indexing
- Per-guild filtering via metadata queries

---

## 11. Future Enhancements

1. **Adaptive Overlap:**
   - Could adjust overlap based on summary complexity
   - Use semantic similarity to determine optimal overlap

2. **Token Counting:**
   - Replace heuristic with actual tokenizer for accurate counts
   - Use model's tokenizer directly

3. **Collection Strategy:**
   - Consider per-guild summary collections if volume is high
   - Add collection cleanup for old meetings

4. **Metadata Enrichment:**
   - Add timestamps for summaries
   - Track summary word count, sentence count
   - Add hash for duplicate detection

---

## 12. Summary of Changes

### Files Modified
1. `source/server/db_models.py` - Added validators
2. `source/services/text_embedding_manager/manager.py` - Added summary embedding logic
3. `source/services/recording_sql_manager/manager.py` - Added transcript_ids update method
4. `source/services/transcription_job_manager/manager.py` - Track user mapping
5. `source/services/summarization_job_manager/manager.py` - Update meeting_summary path

### Files Created
1. `source/services/text_embedding_manager/summary_partitioner.py` - New partitioning system

### Key Features Implemented
✅ JSON format validators for SQL models  
✅ Token-based summary text partitioner  
✅ Subsummary level tracking in embeddings  
✅ Dedicated "summaries" ChromaDB collection  
✅ Meeting transcript_ids format update  
✅ Meeting summary path tracking  
✅ Overlapping segment generation for summaries  
✅ Sentence-aware text splitting  

---

## Contact

For questions or issues related to this implementation, refer to:
- Git branch: `COMP-21_add-summary-embeddings`
- Related ticket: COMP-21

---

*Document Version: 1.0*  
*Last Updated: November 22, 2025*
