# Two-Tier SQL Recording Storage Integration Guide

## Overview

This document outlines how the two-tier SQL recording storage system integrates with the Discord recording architecture.

## Architecture Components

### 1. SQL Models (`source/server/sql_models.py`)

#### `TempRecordingModel`
Tracks transient chunks created during active recording sessions.

**Fields:**
- `id`: UUID (16 chars)
- `meeting_id`: Foreign key to meetings table
- `user_id`: Discord User ID
- `guild_id`: Discord Guild ID
- `created_at`: Timestamp when PCM chunk was created
- `completed_at`: Timestamp when transcoding completed
- `pcm_path`: Path to PCM file
- `mp3_path`: Path to MP3 file (populated after transcode)
- `transcode_status`: QUEUED | IN_PROGRESS | DONE | FAILED
- `sha256`: SHA256 hash of MP3 (populated after transcode)
- `duration_ms`: Duration estimate in milliseconds
- `cleaned`: Boolean flag (0/1) indicating if PCM was deleted

#### `RecordingModel`
Persistent storage for finalized meeting recordings.

**Fields:**
- `id`: UUID (16 chars)
- `meeting_id`: Foreign key to meetings table
- `created_at`: Creation timestamp
- `duration_in_ms`: Total duration
- `sha256`: SHA256 hash
- `filename`: Recording filename

### 2. SQL Recording Service (`source/services/recording_sql/manager.py`)

Provides CRUD operations for both temp and persistent recordings.

**Key Methods:**

#### Temp Recording Operations
- `insert_temp_recording()` - Create new temp chunk record
- `update_temp_recording_transcode_started()` - Mark transcode in progress
- `update_temp_recording_transcode_completed()` - Mark transcode done
- `update_temp_recording_transcode_failed()` - Mark transcode failed
- `mark_temp_recording_cleaned()` - Mark PCM deleted
- `get_temp_recordings_for_meeting()` - Query temp chunks
- `delete_temp_recordings()` - Remove temp records

#### Persistent Recording Operations
- `insert_persistent_recording()` - Create persistent record
- `promote_temp_recordings_to_persistent()` - Aggregate temp → persistent

---

## Integration Points

### Phase 1: Flush Cycle (SessionHandler)

**When:** Each time `_flush_once()` creates a new PCM file

**Action:** Insert temp recording record

**Example Integration:**

```python
class DiscordSessionHandler:
    def __init__(self, channel_id: int, meeting_id: str, user_id: str, guild_id: str):
        self.channel_id = channel_id
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.guild_id = guild_id
        self.is_recording = False
        # ... existing attributes

    async def _flush_once(self, services_manager):
        """Flush buffered PCM data to disk and queue for transcoding."""
        # ... existing PCM write logic
        pcm_path = await self._write_pcm_chunk(data)
        
        # ✅ INSERT TEMP RECORDING
        temp_id = await services_manager.sql_recording_service.insert_temp_recording(
            meeting_id=self.meeting_id,
            user_id=self.user_id,
            guild_id=self.guild_id,
            pcm_path=pcm_path,
        )
        
        # Queue FFmpeg job with temp_id for tracking
        await services_manager.ffmpeg_service_manager.queue_pcm_to_mp3_job(
            pcm_path=pcm_path,
            temp_recording_id=temp_id,
        )
```

---

### Phase 2: FFmpeg Transcode (FFmpegManager)

**When:** FFmpeg conversion job starts/completes/fails

**Actions:**
1. **Job Start:** Update transcode status to IN_PROGRESS
2. **Job Complete:** Update with MP3 path, status DONE, optional SHA256/duration
3. **Job Fail:** Update status to FAILED
4. **PCM Cleanup:** Mark temp recording as cleaned

**Example Integration:**

```python
class FFmpegManagerService(BaseFFmpegServiceManager):
    async def _process_transcode_job(self, job: FFJob, temp_recording_id: str):
        """Process a single transcode job with SQL tracking."""
        
        # ✅ UPDATE: Transcode started
        await self.services.sql_recording_service.update_temp_recording_transcode_started(
            temp_recording_id
        )
        
        try:
            # Run FFmpeg conversion
            success, stdout, stderr = self.handler.convert_file(
                input_path=job.input_path,
                output_path=job.output_path,
                options=job.options,
            )
            
            if success:
                # ✅ UPDATE: Transcode completed
                sha256 = await self._compute_sha256(job.output_path)
                duration_ms = await self._get_audio_duration(job.output_path)
                
                await self.services.sql_recording_service.update_temp_recording_transcode_completed(
                    temp_recording_id=temp_recording_id,
                    mp3_path=job.output_path,
                    sha256=sha256,
                    duration_ms=duration_ms,
                )
                
                # ✅ DELETE PCM and mark cleaned
                await self._delete_pcm_file(job.input_path)
                await self.services.sql_recording_service.mark_temp_recording_cleaned(
                    temp_recording_id
                )
            else:
                # ✅ UPDATE: Transcode failed
                await self.services.sql_recording_service.update_temp_recording_transcode_failed(
                    temp_recording_id
                )
                await self.services.logging_service.error(
                    f"Transcode failed for {temp_recording_id}: {stderr}"
                )
        except Exception as e:
            await self.services.sql_recording_service.update_temp_recording_transcode_failed(
                temp_recording_id
            )
            await self.services.logging_service.error(
                f"Exception during transcode: {e}"
            )
```

---

### Phase 3: Session End (RecorderManager)

**When:** Recording session stops

**Action:** Promote temp chunks to persistent recording

**Example Integration:**

```python
class DiscordRecorderManagerService(BaseDiscordRecorderServiceManager):
    async def stop_session(self, channel_id: int) -> bool:
        """Stop recording and promote temp chunks to persistent storage."""
        session = self.sessions.get(channel_id)
        if not session:
            return False
        
        # Stop recording
        session.is_recording = False
        
        # Wait for all pending transcodes to complete
        await self._wait_for_pending_transcodes(session.meeting_id)
        
        # ✅ PROMOTE temp recordings to persistent
        recording_id = await self.services.sql_recording_service.promote_temp_recordings_to_persistent(
            meeting_id=session.meeting_id,
            user_id=session.user_id,  # Optional: per-user or meeting-wide
        )
        
        if recording_id:
            await self.services.logging_service.info(
                f"Session ended. Created persistent recording: {recording_id}"
            )
        
        # Update meeting status
        # await self._update_meeting_status(session.meeting_id, MeetingStatus.PROCESSING)
        
        # Cleanup session
        del self.sessions[channel_id]
        return True
    
    async def _wait_for_pending_transcodes(self, meeting_id: str):
        """Wait for all temp recordings to reach DONE or FAILED status."""
        max_wait_seconds = 300  # 5 minutes timeout
        start_time = datetime.utcnow()
        
        while True:
            chunks = await self.services.sql_recording_service.get_temp_recordings_for_meeting(
                meeting_id
            )
            
            pending = [
                c for c in chunks 
                if c["transcode_status"] in ["queued", "in_progress"]
            ]
            
            if not pending:
                break
            
            if (datetime.utcnow() - start_time).total_seconds() > max_wait_seconds:
                await self.services.logging_service.warning(
                    f"Timeout waiting for transcodes on meeting {meeting_id}"
                )
                break
            
            await asyncio.sleep(2)  # Poll every 2 seconds
```

---

## Lifecycle Summary Table

| Phase                | Action                        | Table                         | Status Transition       |
| -------------------- | ----------------------------- | ----------------------------- | ----------------------- |
| **Flush**            | Create PCM + insert DB record | `temp_recordings` (INSERT)    | → QUEUED                |
| **FFmpeg Start**     | Update transcode status       | `temp_recordings` (UPDATE)    | QUEUED → IN_PROGRESS    |
| **FFmpeg Complete**  | Update with MP3 path          | `temp_recordings` (UPDATE)    | IN_PROGRESS → DONE      |
| **PCM Cleanup**      | Mark cleaned                  | `temp_recordings` (UPDATE)    | cleaned = 1             |
| **Session End**      | Aggregate chunks              | `recordings` (INSERT)         | Create persistent entry |
| **Cleanup Job**      | Remove processed temp rows    | `temp_recordings` (DELETE)    | Remove stale records    |

---

## Responsibility Ownership

| Component              | Responsibility                                    |
| ---------------------- | ------------------------------------------------- |
| **SessionHandler**     | Insert temp recording on PCM flush                |
| **FFmpegManager**      | Update transcode status throughout job lifecycle  |
| **RecorderManager**    | Promote temp → persistent on session stop         |
| **Cleanup Job**        | Delete old temp records (optional background task)|

---

## Benefits

1. **Memory Safety:** Long recordings broken into manageable chunks
2. **Resilience:** Partial chunks discoverable in `temp_recordings` if crash occurs
3. **Traceability:** Full transcode status tracking for debugging
4. **Clean Separation:** Temp vs persistent storage hierarchy
5. **Meeting Hierarchy:** Follows meeting → recording relationship

---

## Migration Checklist

- [ ] Update `ServicesManager` to include `sql_recording_service`
- [ ] Add `sql_recording_service` to service initialization in `constructor.py`
- [ ] Update `DiscordSessionHandler` to accept `meeting_id`, `user_id`, `guild_id` in constructor
- [ ] Implement `_flush_once()` method in `SessionHandler` with temp recording insert
- [ ] Modify FFmpeg job queue to accept and track `temp_recording_id`
- [ ] Add SHA256/duration computation utilities to FFmpegManager
- [ ] Implement `_wait_for_pending_transcodes()` in RecorderManager
- [ ] Create database migration to add new `temp_recordings` columns
- [ ] Add optional background cleanup job for old temp records (TTL-based)
- [ ] Update meeting status workflow to include recording compilation phase

---

## Example Full Flow

### 1. User starts recording in Discord channel

```python
# RecorderManager.start_session()
meeting_id = generate_16_char_uuid()
session = DiscordSessionHandler(
    channel_id=123456,
    meeting_id=meeting_id,
    user_id="987654321",
    guild_id="111222333",
)
session.start_recording()
```

### 2. Every 10 seconds, flush cycle runs

```python
# SessionHandler._flush_once()
temp_id_1 = await sql_recording_service.insert_temp_recording(...)  # chunk_0001
temp_id_2 = await sql_recording_service.insert_temp_recording(...)  # chunk_0002
# ... status: QUEUED
```

### 3. FFmpeg processes each chunk

```python
# FFmpegManager processes jobs
await sql_recording_service.update_temp_recording_transcode_started(temp_id_1)
# ... ffmpeg runs
await sql_recording_service.update_temp_recording_transcode_completed(temp_id_1, mp3_path=...)
await sql_recording_service.mark_temp_recording_cleaned(temp_id_1)
# ... status: DONE, cleaned=1
```

### 4. User stops recording

```python
# RecorderManager.stop_session()
await _wait_for_pending_transcodes(meeting_id)
recording_id = await sql_recording_service.promote_temp_recordings_to_persistent(meeting_id)
# Creates single persistent recording entry, deletes temp records
```

### 5. Database state

**temp_recordings:** (deleted after promotion, or retained for audit)

**recordings:**
```
id: abc123...
meeting_id: xyz789...
duration_in_ms: 125000  (aggregated from all chunks)
filename: recording_xyz789_987654321.mp3
sha256: def456...
```

---

## Advanced: Promotion Strategies

### Strategy 1: Per-User Recordings
- Keep separate recordings for each participant
- Use `user_id` filter in promotion
- Result: One `recordings` entry per user per meeting

### Strategy 2: Single Meeting Recording
- Merge all participants into one file
- Require audio mixing step before promotion
- Result: One `recordings` entry per meeting

### Strategy 3: Hybrid
- Store individual user chunks in `recordings`
- Create additional "mixed" recording for full meeting
- Result: N+1 recordings (N users + 1 mixed)

Choose based on your transcription and playback requirements.

---

## Troubleshooting

### Issue: Temp recordings stuck in QUEUED
**Cause:** FFmpeg queue not processing jobs
**Solution:** Check FFmpeg service health, verify job queue is running

### Issue: Promotion fails with no completed chunks
**Cause:** All transcodes failed or still in progress
**Solution:** Check transcode error logs, ensure adequate wait time

### Issue: Duplicate temp recordings
**Cause:** Flush called multiple times for same chunk
**Solution:** Add idempotency check in flush cycle

### Issue: Orphaned temp recordings
**Cause:** Session crashed before promotion
**Solution:** Implement background cleanup job with TTL (e.g., delete after 24h)

---

## Next Steps

Would you like me to:
1. ✅ Implement the actual SessionHandler flush integration?
2. ✅ Create the FFmpeg job tracking modifications?
3. ✅ Build the background cleanup job for old temp records?
4. ✅ Create database migration scripts for the new schema?
5. ✅ Add utility methods for SHA256/duration computation?

Let me know which piece you'd like to tackle next!
