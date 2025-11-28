# Attachment Download System

## Overview

When users send files, images, videos, or other attachments to the bot, Discord provides URLs to access those files. The bot now automatically downloads these files to temporary storage before processing them with the LLM.

## How It Works

### 1. Message Reception
```
User sends: "Analyze this code" [attaches script.py]
                ↓
Discord provides URL: https://cdn.discordapp.com/.../script.py
                ↓
Bot extracts attachment metadata
```

### 2. Download Process
```python
# Before LLM processing, attachments are downloaded:
await self._download_attachments_for_processing(attachments)

# Downloads to: /path/to/recordings/temp/script.py
# Tracks download for cleanup
```

### 3. LLM Context
```
LLM receives:
"[2025-11-26_14-30] User <@123>: Analyze this code
[Attachments:]
1. FILE 'script.py'
   Downloaded: Yes (available for processing)
   Local Path: /absolute/path/to/temp/script.py
   URL: https://cdn.discordapp.com/.../script.py"
```

### 4. Automatic Cleanup
```python
# After AI responds, files are automatically deleted:
await self._cleanup_downloaded_attachments()

# Temp directory cleaned up
```

## Architecture

### Temp Storage Location
Uses dedicated conversation temp directory:
```
assets/data/conversations/temp/
```

This is separate from the recording temp storage and specifically for conversation attachments.

### Download Function
```python
async def download_attachment(
    url: str,
    temp_dir: str,
    filename: str | None = None,
    max_size_mb: int = 50,
) -> str | None:
```

**Features:**
- Downloads files from Discord CDN URLs
- Streams in chunks to handle large files
- Respects size limits (default 50MB)
- Extracts filename from URL if not provided
- Returns absolute path to downloaded file
- Cleans up partial files on error

### Batch Download
```python
async def download_attachments_batch(
    attachments: list[dict[str, Any]],
    temp_dir: str,
    max_size_mb: int = 50,
) -> list[dict[str, Any]]:
```

**Features:**
- Downloads multiple attachments concurrently
- Updates metadata with `local_path` and `downloaded` status
- Skips URLs and embeds (don't need downloading)
- Continues on individual failures

### Cleanup Function
```python
async def cleanup_attachment_files(
    attachments: list[dict[str, Any]]
) -> int:
```

**Features:**
- Deletes all downloaded files
- Uses `local_path` from metadata
- Silently ignores missing files
- Returns count of deleted files

## Download Flow in ChatJob

### Single Message Processing
```python
async def _process_user_message(self, message, user_id, attachments):
    # 1. Add message to conversation
    # 2. Save conversation
    # 3. Set status to THINKING
    # 4. Download attachments ← NEW
    await self._download_attachments_for_processing(attachments)
    # 5. Build LLM messages (includes downloaded file paths)
    # 6. Call LLM
    # 7. Send response
    # 8. Cleanup attachments ← NEW
    await self._cleanup_downloaded_attachments()
    # 9. Save conversation
```

### Batch Message Processing
```python
async def _process_message_queue(self):
    # 1. Collect messages from queue
    # 2. Add all messages to conversation
    # 3. Download attachments from ALL messages ← NEW
    for msg in messages_to_process:
        if msg.attachments:
            await self._download_attachments_for_processing(msg.attachments)
    # 4. Build LLM messages
    # 5. Call LLM
    # 6. Send response
    # 7. Cleanup ALL downloaded attachments ← NEW
    await self._cleanup_downloaded_attachments()
    # 8. Save conversation
```

## Configuration

### Size Limits
```python
# Default: 50MB per file
max_size_mb = 50

# Configurable in download_attachment() call
local_path = await download_attachment(
    url=url,
    temp_dir=temp_dir,
    max_size_mb=100,  # Custom limit
)
```

### Timeout
```python
# Default: 60 seconds per download
timeout=aiohttp.ClientTimeout(total=60)
```

### Temp Directory
```python
# Uses conversation file manager's temp path
temp_dir = self.services.conversation_file_service_manager.get_temp_storage_path()
# Returns: /absolute/path/to/assets/data/conversations/temp
```

**Features:**
- Separate from recording temp storage
- Automatically created on service startup
- Automatically cleaned on service shutdown
- Dedicated to conversation attachments only

## Error Handling

### Download Failures
- Download failure does NOT block message processing
- Attachment marked as `downloaded: False`
- LLM context shows "Downloaded: Failed"
- User can see which attachments failed

### Partial Downloads
- If download exceeds size limit mid-stream, partial file is deleted
- Returns `None` to indicate failure

### Cleanup Errors
- Cleanup failures are silently ignored
- Files may remain in temp dir until next bot restart
- Temp dir is cleared on bot shutdown (existing behavior)

## Future Enhancements

### 1. **File Content Reading**
```python
# Read text files and include content in LLM context
if local_path.endswith('.txt'):
    with open(local_path, 'r') as f:
        content = f.read()
    # Add content to LLM message
```

### 2. **Image Analysis**
```python
# Pass images to vision-capable LLM
if att_type == 'image' and local_path:
    image_data = open(local_path, 'rb').read()
    # Send to vision model
```

### 3. **PDF Parsing**
```python
# Extract text from PDFs
if local_path.endswith('.pdf'):
    text = extract_pdf_text(local_path)
    # Include in LLM context
```

### 4. **Code Analysis**
```python
# Parse code files with syntax highlighting
if local_path.endswith(('.py', '.js', '.java')):
    code = open(local_path, 'r').read()
    # Format with syntax highlighting
```

## Monitoring

### Logging
```python
# Download started
"Downloaded 3/5 attachments for thread {thread_id}"

# Cleanup completed
"Cleaned up 3 attachment files for thread {thread_id}"
```

### Tracking
```python
# ChatJob tracks all downloaded files
self._downloaded_attachments = [
    {"local_path": "/path/to/file1.png", "downloaded": True},
    {"local_path": "/path/to/file2.pdf", "downloaded": True},
]
```

## Security Considerations

### 1. **File Size Limits**
- Prevents disk space exhaustion
- Default 50MB per file
- Configurable per use case

### 2. **Automatic Cleanup**
- Prevents temp directory growth
- Files deleted immediately after use
- No permanent storage of user files

### 3. **URL Validation**
- Downloads only from Discord CDN
- Timeout prevents hanging
- Error handling prevents crashes

### 4. **Path Safety**
- Uses os.path.join for safe path construction
- Validates temp directory existence
- Handles special characters in filenames
