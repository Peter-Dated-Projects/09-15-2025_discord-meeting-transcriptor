# Quick Start Guide: Two-Tier SQL Recording Storage

This guide provides the fastest path to integrating the two-tier SQL recording storage system into your Discord bot.

## 🚀 5-Minute Setup

### Step 1: Database Migration (2 min)

The `TempRecordingModel` has been enhanced with new columns. Apply this migration:

```sql
-- Add new columns to temp_recordings table
ALTER TABLE temp_recordings
ADD COLUMN user_id VARCHAR(20) NOT NULL,
ADD COLUMN guild_id VARCHAR(20) NOT NULL,
ADD COLUMN completed_at DATETIME NULL,
ADD COLUMN pcm_path VARCHAR(512) NOT NULL,
ADD COLUMN mp3_path VARCHAR(512) NULL,
ADD COLUMN transcode_status ENUM('queued', 'in_progress', 'done', 'failed') NOT NULL DEFAULT 'queued',
ADD COLUMN sha256 VARCHAR(64) NULL,
ADD COLUMN duration_ms INT NULL,
ADD COLUMN cleaned TINYINT NOT NULL DEFAULT 0;

-- Add indexes for performance
CREATE INDEX idx_temp_recordings_user_id ON temp_recordings(user_id);
CREATE INDEX idx_temp_recordings_guild_id ON temp_recordings(guild_id);
CREATE INDEX idx_temp_recordings_status ON temp_recordings(transcode_status);

-- Drop old filename column (if it exists)
-- ALTER TABLE temp_recordings DROP COLUMN filename;
```

### Step 2: Wire Up Service (1 min)

Update your service constructor (e.g., `source/constructor.py`):

```python
from source.services.recording_sql.manager import SQLRecordingManagerService

# In your constructor function:
sql_recording_service = SQLRecordingManagerService(server)

services = ServicesManager(
    server=server,
    file_service_manager=file_service,
    recording_file_service_manager=recording_file_service,
    transcription_file_service_manager=transcription_file_service,
    ffmpeg_service_manager=ffmpeg_service,
    logging_service=logging_service,
    sql_recording_service=sql_recording_service,  # ✅ Add this
)
```

### Step 3: Update SessionHandler (1 min)

Modify your `DiscordSessionHandler` constructor:

```python
class DiscordSessionHandler:
    def __init__(
        self,
        channel_id: int,
        meeting_id: str,  # ✅ Add
        user_id: str,     # ✅ Add
        guild_id: str,    # ✅ Add
        services: ServicesManager,  # ✅ Add
    ):
        self.channel_id = channel_id
        self.meeting_id = meeting_id
        self.user_id = user_id
        self.guild_id = guild_id
        self.services = services
        self.is_recording = False
```

### Step 4: Add Flush Integration (1 min)

Add this method to your `DiscordSessionHandler`:

```python
async def _flush_once(self):
    """Flush audio buffer to disk and track in SQL."""
    if len(self._audio_buffer) == 0:
        return
    
    # Write PCM file
    pcm_path = await self._write_pcm_file(self._audio_buffer)
    
    # ✅ INSERT temp recording
    temp_id = await self.services.sql_recording_service.insert_temp_recording(
        meeting_id=self.meeting_id,
        user_id=self.user_id,
        guild_id=self.guild_id,
        pcm_path=pcm_path,
    )
    
    # Queue FFmpeg job
    mp3_path = pcm_path.replace('.pcm', '.mp3')
    await self.services.ffmpeg_service_manager.queue_pcm_to_mp3_job(
        input_path=pcm_path,
        output_path=mp3_path,
        options={...},
        temp_recording_id=temp_id,  # ✅ Pass for tracking
    )
    
    self._audio_buffer.clear()
```

### Step 5: Test (30 seconds)

Run your bot and start a recording session. Check SQL:

```sql
SELECT * FROM temp_recordings ORDER BY created_at DESC LIMIT 5;
```

You should see new records with `transcode_status = 'queued'`.

---

## 📝 Minimal Working Example

Here's the absolute minimum code to get started:

```python
# 1. Start session
meeting_id = generate_16_char_uuid()
session = DiscordSessionHandler(
    channel_id=123456,
    meeting_id=meeting_id,
    user_id="987654321",
    guild_id="111222333",
    services=services_manager,
)

# 2. On flush (every 10s)
temp_id = await services_manager.sql_recording_service.insert_temp_recording(
    meeting_id=meeting_id,
    user_id="987654321",
    guild_id="111222333",
    pcm_path="/path/to/chunk.pcm",
)

# 3. On FFmpeg start
await services_manager.sql_recording_service.update_temp_recording_transcode_started(temp_id)

# 4. On FFmpeg complete
await services_manager.sql_recording_service.update_temp_recording_transcode_completed(
    temp_recording_id=temp_id,
    mp3_path="/path/to/chunk.mp3",
    sha256="abc123...",
    duration_ms=10000,
)

# 5. On session end
recording_id = await services_manager.sql_recording_service.promote_temp_recordings_to_persistent(
    meeting_id=meeting_id,
)
```

---

## 🎯 What You Get

After completing the 5-minute setup:

✅ **Temp recordings** tracked in SQL  
✅ **Transcode status** updated automatically  
✅ **Crash resilience** - partial chunks discoverable  
✅ **Clean promotion** - temp → persistent on session end  
✅ **No breaking changes** - existing code continues to work  

---

## 📚 Next Steps

- **Read Full Documentation**: `INTEGRATION_GUIDE_TWO_TIER_STORAGE.md`
- **Review Examples**: `source/services/*/manager_example.py`
- **Implement FFmpeg Tracking**: See `manager_example.py` for complete worker logic
- **Add Promotion Flow**: See `promotion_example.py` for session end handling
- **Enable Cleanup**: Add background task for old temp records

---

## ⚠️ Common Pitfalls

1. **Forgetting to pass `temp_recording_id`** to FFmpeg jobs
   - **Fix**: Update job queue signature to accept `temp_recording_id`

2. **Not waiting for transcodes** before promotion
   - **Fix**: Implement `_wait_for_pending_transcodes()` method

3. **Meeting ID doesn't exist** in meetings table
   - **Fix**: Create meeting record before starting session

4. **SQL service not initialized**
   - **Fix**: Add to `ServicesManager` and call `on_start()`

---

## 🆘 Need Help?

1. Check `IMPLEMENTATION_SUMMARY_TWO_TIER_STORAGE.md` for complete overview
2. Review example code in `source/services/discord_recorder/session_handler_example.py`
3. Examine SQL service in `source/services/recording_sql/manager.py`
4. Read integration guide in `INTEGRATION_GUIDE_TWO_TIER_STORAGE.md`

---

## ✨ That's It!

You now have a robust two-tier SQL recording storage system. The minimal setup takes **5 minutes**, and you can incrementally add features like:
- FFmpeg status tracking
- Promotion on session end
- Background cleanup
- Retry logic
- Progress dashboards

Start simple, then enhance as needed. Good luck! 🚀
