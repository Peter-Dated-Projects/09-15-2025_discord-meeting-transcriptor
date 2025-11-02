# Discord Recorder Manager - Usage Examples

## Quick Start

### 1. Starting a Recording Session

```python
# From a Discord bot command or event handler
recorder_manager = services.discord_recorder_service

# Start recording in a voice channel
success = await recorder_manager.start_session(
    channel_id=123456789,  # Discord voice channel ID
    meeting_id="abc123xyz7890def",  # Optional: generated if not provided
    user_id="987654321098765432",  # Discord user ID
    guild_id="111222333444555666",  # Discord guild/server ID
)

if success:
    print("Recording started!")
```

### 2. Pushing Audio Data

```python
# In your Discord voice receiver callback
# This is typically called by discord.py's VoiceClient

async def on_voice_data(user_id: int, pcm_audio: bytes):
    """Called when audio data is received from Discord."""
    session = recorder_manager.sessions.get(channel_id)
    if session:
        await session.push_audio_data(pcm_audio)
```

### 3. Checking Session Status

```python
# Get status for a specific session
status = await recorder_manager.get_session_status(channel_id)
print(f"Recording: {status['is_recording']}")
print(f"Total chunks: {status['total_chunks']}")
print(f"Chunk statuses: {status['chunk_statuses']}")

# List all active sessions
active_sessions = await recorder_manager.list_active_sessions()
for session in active_sessions:
    print(f"Meeting {session['meeting_id']}: {session['total_chunks']} chunks")
```

### 4. Pausing/Resuming

```python
# Pause recording (stops flush cycle but keeps session alive)
await recorder_manager.pause_session(str(channel_id))

# Resume recording
await recorder_manager.resume_session(str(channel_id))
```

### 5. Stopping and Promoting

```python
# Stop recording and promote temp recordings to persistent storage
success = await recorder_manager.stop_session(channel_id)

# This will:
# 1. Stop the recording session
# 2. Wait for all pending transcodes to complete (up to 5 minutes)
# 3. Promote temp recordings to a persistent recording entry
# 4. Clean up the session
```

## Complete Discord Bot Example

```python
import discord
from discord.ext import commands

# Assuming you have ServicesManager initialized
services = get_services_manager()

bot = commands.Bot(command_prefix="!")

@bot.command()
async def start_recording(ctx):
    """Start recording the voice channel."""
    if not ctx.author.voice:
        await ctx.send("You must be in a voice channel!")
        return
    
    channel = ctx.author.voice.channel
    guild = ctx.guild
    
    # Generate meeting ID
    from source.utils import generate_16_char_uuid
    meeting_id = generate_16_char_uuid()
    
    # Start recording session
    success = await services.discord_recorder_service.start_session(
        channel_id=channel.id,
        meeting_id=meeting_id,
        user_id=str(ctx.author.id),
        guild_id=str(guild.id),
    )
    
    if success:
        await ctx.send(f"✅ Started recording in {channel.name}")
    else:
        await ctx.send("❌ Failed to start recording")

@bot.command()
async def stop_recording(ctx):
    """Stop recording the voice channel."""
    if not ctx.author.voice:
        await ctx.send("You must be in a voice channel!")
        return
    
    channel = ctx.author.voice.channel
    
    # Stop recording session
    await ctx.send("⏳ Stopping recording and processing chunks...")
    success = await services.discord_recorder_service.stop_session(channel.id)
    
    if success:
        await ctx.send("✅ Recording stopped and saved!")
    else:
        await ctx.send("❌ No active recording in this channel")

@bot.command()
async def recording_status(ctx):
    """Get recording status for the current channel."""
    if not ctx.author.voice:
        await ctx.send("You must be in a voice channel!")
        return
    
    channel = ctx.author.voice.channel
    status = await services.discord_recorder_service.get_session_status(channel.id)
    
    if not status:
        await ctx.send("No active recording in this channel")
        return
    
    # Format status message
    chunks = status['chunk_statuses']
    message = f"""
📊 **Recording Status**
Meeting ID: `{status['meeting_id']}`
Recording: {'✅ Active' if status['is_recording'] else '⏸️ Paused'}
Total Chunks: {status['total_chunks']}

**Chunk Processing:**
⏳ Queued: {chunks['queued']}
🔄 Processing: {chunks['in_progress']}
✅ Done: {chunks['done']}
❌ Failed: {chunks['failed']}

Buffer Size: {status['buffer_size_bytes']} bytes
    """
    await ctx.send(message)

bot.run("YOUR_BOT_TOKEN")
```

## Advanced: Custom Audio Processing

```python
class CustomDiscordSessionHandler(DiscordSessionHandler):
    """Extended session handler with custom audio processing."""
    
    async def push_audio_data(self, pcm_data: bytes) -> None:
        """Override to add custom audio processing."""
        # Apply noise reduction, normalization, etc.
        processed_data = await self.process_audio(pcm_data)
        
        # Call parent method
        await super().push_audio_data(processed_data)
    
    async def process_audio(self, pcm_data: bytes) -> bytes:
        """Custom audio processing."""
        # Your audio processing logic here
        return pcm_data
```

## Lifecycle Events

The manager automatically handles:

1. **Flush Cycle** (every 10 seconds)
   - Writes PCM chunk to temp storage
   - Inserts temp_recording in SQL (status: QUEUED)
   - Queues FFmpeg transcode job

2. **FFmpeg Processing** (background workers)
   - Updates status: QUEUED → IN_PROGRESS
   - Transcodes PCM → MP3
   - Updates status: IN_PROGRESS → DONE
   - Deletes PCM file, marks as cleaned

3. **Session Stop**
   - Waits for pending transcodes (up to 5 minutes)
   - Promotes temp recordings → persistent recording
   - Deletes temp recording records
   - Cleans up session

4. **Background Cleanup** (every hour)
   - Finds temp recordings older than 24 hours
   - Deletes associated files
   - Removes SQL records

## Monitoring

```python
# Check active sessions
sessions = await recorder_manager.list_active_sessions()
print(f"Active sessions: {len(sessions)}")

# Monitor temp recordings for a meeting
chunks = await services.sql_recording_service.get_temp_recordings_for_meeting(
    meeting_id="abc123xyz7890def"
)
print(f"Total chunks: {len(chunks)}")
for chunk in chunks:
    print(f"  {chunk['id']}: {chunk['transcode_status']}")
```

## Error Handling

```python
try:
    success = await recorder_manager.start_session(
        channel_id=channel_id,
        user_id=user_id,
        guild_id=guild_id,
    )
except Exception as e:
    await services.logging_service.error(f"Failed to start session: {e}")
    # Handle error appropriately
```

## Best Practices

1. **Always provide user_id and guild_id** for SQL tracking
2. **Check session existence** before stopping
3. **Monitor chunk statuses** during long recordings
4. **Handle timeouts** gracefully (5-minute transcode wait)
5. **Use pause/resume** instead of stop/start for temporary breaks
6. **Monitor background cleanup** logs for file deletion issues

## Configuration

```python
# Adjust flush interval (default: 10 seconds)
session._flush_task = asyncio.create_task(session._flush_loop())

# Adjust transcode wait timeout (default: 5 minutes)
await recorder_manager._wait_for_pending_transcodes(
    meeting_id=meeting_id,
    max_wait_seconds=600,  # 10 minutes
)

# Adjust cleanup TTL (default: 24 hours)
await recorder_manager._cleanup_old_temp_recordings_once(ttl_hours=48)
```
