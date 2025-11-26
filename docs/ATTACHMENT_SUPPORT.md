# Attachment Support in Chat Conversations

## Overview

The chat system now supports URLs, images, and files in user messages. When users include attachments or URLs in their messages, the bot will have access to this information and can reference it in responses.

## Features

### 1. **Attachment Extraction**
- **Discord attachments**: Images, documents, videos, audio files
- **Embedded URLs**: Links in message content are automatically detected
- **Embeds**: Images and thumbnails from Discord embeds

### 2. **Attachment Metadata**
Each attachment is stored with the following metadata:
```python
{
    "type": "image" | "file" | "url" | "embed" | "video" | "audio",
    "url": str,
    "filename": str (optional),
    "content_type": str (optional),
    "size": int (optional, in bytes),
    "description": str (optional)
}
```

### 3. **Message Batching with Attachments**
When the AI is thinking and users send multiple messages:
- Messages are queued with their attachments
- Up to 5 messages can be batched together
- Each message's attachments are preserved individually
- The bot processes all messages and attachments in a single response

## Technical Implementation

### Data Structure Updates

#### `Message` Class (in_memory_cache.py)
```python
@dataclass
class Message:
    created_at: datetime
    message_type: MessageType
    message_content: str
    tools: Optional[List[Dict[str, Any]]] = None
    requester: Optional[str] = None
    attachments: Optional[List[Dict[str, Any]]] = None  # NEW
```

#### `QueuedUserMessage` Class (manager.py)
```python
@dataclass
class QueuedUserMessage:
    user_id: str
    content: str
    timestamp: datetime
    attachments: list[dict] = field(default_factory=list)  # NEW
```

### Processing Flow

1. **Message Reception** (`cogs/chat.py`)
   - Extract attachments using `extract_attachments_from_message()`
   - Pass attachments to `create_and_queue_chat_job()` or `queue_user_message()`

2. **Job Creation** (`chat_job_manager/manager.py`)
   - Store attachments in job's message queue
   - Track attachments through processing pipeline

3. **LLM Context Building** (`_build_llm_messages()`)
   - Format attachment information for LLM
   - Include URLs, filenames, types in context
   - Append to user message content

4. **Conversation Storage**
   - Attachments saved in JSON format in `meta.attachments`
   - Persisted to disk with conversation history

## Usage Examples

### Example 1: Image Attachment
```
User: "What's in this image?" [attaches cat.jpg]

Bot receives:
- message_content: "What's in this image?"
- attachments: [
    {
        "type": "image",
        "url": "https://cdn.discordapp.com/...",
        "filename": "cat.jpg",
        "content_type": "image/jpeg",
        "size": 245678
    }
]

LLM sees:
"[2025-11-26_14-30] User123 <@123456>: What's in this image?
[Attachments:]
1. IMAGE 'cat.jpg'
   URL: https://cdn.discordapp.com/..."
```

### Example 2: Multiple Messages with Attachments (Batching)
```
User: "Check this out" [attaches document.pdf]
(Bot is thinking...)
User: "Also this" [attaches screenshot.png]
(Bot is thinking...)
User: "And read this" [sends URL to article]

Bot processes all 3 messages together:
- Message 1: document.pdf attachment
- Message 2: screenshot.png attachment  
- Message 3: URL extracted from content
```

### Example 3: URL Detection
```
User: "What do you think about this? https://example.com/article"

Bot receives:
- message_content: "What do you think about this? https://example.com/article"
- attachments: [
    {
        "type": "url",
        "url": "https://example.com/article"
    }
]
```

## Utility Functions

### `attachment_utils.py`

#### `extract_attachments_from_message(message: discord.Message)`
Extracts all attachments and URLs from a Discord message.

#### `extract_urls_from_text(text: str)`
Uses regex to find all URLs in text content.

#### `download_image_as_bytes(url: str, max_size_mb: int = 10)`
Downloads image data from URL (for future vision model support).

#### `fetch_url_content(url: str, max_length: int = 5000)`
Fetches text content from URL (for future RAG integration).

#### `format_attachments_for_llm(attachments: list[dict])`
Formats attachment metadata into readable text for LLM context.

#### `process_attachments_for_context(attachments: list[dict], download_images: bool = False)`
Prepares attachments for LLM, optionally downloading images.

## Future Enhancements

### 1. **Vision Model Support**
- Download images and pass to vision-capable LLMs
- Analyze image content directly
- Extract text from images (OCR)

### 2. **URL Content Fetching**
- Automatically fetch and summarize webpage content
- Extract key information from linked articles
- Add URL content to conversation context

### 3. **File Processing**
- Extract text from PDFs
- Parse spreadsheets and documents
- Process code files

### 4. **Attachment Limits**
- Maximum file sizes per message
- Total attachment size limits per batch
- Rate limiting for downloads

### 5. **Caching**
- Cache downloaded content
- Deduplicate identical URLs/files
- Store processed content in vector DB

## Configuration

### Environment Variables
None currently required. Future options may include:
- `MAX_ATTACHMENT_SIZE_MB`: Maximum attachment size
- `ENABLE_URL_FETCHING`: Auto-fetch URL content
- `ENABLE_IMAGE_ANALYSIS`: Use vision models
- `ATTACHMENT_CACHE_DIR`: Directory for cached content

## API Changes

### Updated Method Signatures

#### `create_and_queue_chat_job()`
```python
async def create_and_queue_chat_job(
    self,
    thread_id: str,
    conversation_id: str,
    message: str,
    user_id: str,
    attachments: list[dict] | None = None,  # NEW
) -> str:
```

#### `queue_user_message()`
```python
async def queue_user_message(
    self,
    thread_id: str,
    message: str,
    user_id: str,
    attachments: list[dict] | None = None,  # NEW
) -> bool:
```

#### `_process_user_message()`
```python
async def _process_user_message(
    self,
    message_content: str,
    user_id: str,
    attachments: list[dict] | None = None,  # NEW
) -> None:
```

## Backward Compatibility

All changes are backward compatible:
- `attachments` parameter is optional (defaults to `None`)
- Existing code without attachments continues to work
- JSON format preserves structure (attachments in `meta`)

## Testing

To test the feature:

1. **Send a message with an image attachment**
   ```
   @Bot Check out this screenshot [attach image]
   ```

2. **Send a message with a URL**
   ```
   @Bot What do you think about https://example.com?
   ```

3. **Send multiple messages while bot is thinking**
   ```
   @Bot Process this [attach file1.pdf]
   (wait for thinking indicator)
   Also this [attach file2.jpg]
   And check this link: https://example.com
   ```

4. **Verify in logs**
   - Check that attachments are extracted
   - Verify they appear in conversation JSON
   - Confirm LLM receives formatted attachment info

## Notes

- Attachments are currently metadata-only (URLs and filenames)
- Actual file content is not downloaded or processed yet
- Vision models and content fetching are planned enhancements
- The bot can reference attachment information in responses
- All attachment metadata is stored in conversation history
