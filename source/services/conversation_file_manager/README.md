# Conversation File Manager Service

## Overview

The `ConversationFileManagerService` is a service that manages the storage and retrieval of conversation JSON files for the Echo Discord bot. It follows the same design patterns as the `RecordingFileManagerService` and `TranscriptionFileManagerService`, providing atomic file operations through the base `FileManagerService`.

## Purpose

This service handles the persistence of user conversations with the Echo bot, storing them as JSON files with a standardized naming convention. Each conversation file contains the full message history and metadata for a specific user in a specific guild on a specific date.

## File Naming Convention

Conversation files follow this naming pattern:

```
yyyy-mm-dd_conversation-with-{discord_user_id}-in-{guild_id}.json
```

**Example:**
```
2025-11-25_conversation-with-123456789012345678-in-987654321098765432.json
```

## Storage Location

Conversation files are stored in:
```
assets/data/conversations/
```

## Core Features

### 1. Save a New Conversation
Save a new conversation JSON file. Raises `FileExistsError` if a conversation already exists for the same user, guild, and date.

```python
filename = await services_manager.conversation_file_service_manager.save_conversation(
    conversation_data={
        "messages": [
            {"role": "user", "content": "Hello!"},
            {"role": "assistant", "content": "Hi! How can I help?"}
        ],
        "metadata": {"created_at": "2025-11-25T10:30:00"}
    },
    discord_user_id="123456789012345678",
    guild_id="987654321098765432"
)
```

### 2. Update an Existing Conversation
Update an existing conversation file with new data using atomic file operations.

```python
success = await services_manager.conversation_file_service_manager.update_conversation(
    filename="2025-11-25_conversation-with-123456789012345678-in-987654321098765432.json",
    conversation_data=updated_conversation_data
)
```

### 3. Retrieve an Existing Conversation
Retrieve a conversation by its filename. Returns `None` if the file doesn't exist.

```python
conversation_data = await services_manager.conversation_file_service_manager.retrieve_conversation(
    filename="2025-11-25_conversation-with-123456789012345678-in-987654321098765432.json"
)
```

### 4. Delete an Existing Conversation
Delete a conversation file. Returns `True` if successful, `False` if the file doesn't exist.

```python
success = await services_manager.conversation_file_service_manager.delete_conversation(
    filename="2025-11-25_conversation-with-123456789012345678-in-987654321098765432.json"
)
```

### 5. Check Conversation Existence
Check if a conversation file exists.

```python
exists = await services_manager.conversation_file_service_manager.conversation_exists(
    filename="2025-11-25_conversation-with-123456789012345678-in-987654321098765432.json"
)
```

### 6. List All Conversations
Get a list of all conversation files in the storage directory.

```python
conversations = await services_manager.conversation_file_service_manager.list_conversations()
# Returns: ['2025-11-25_conversation-with-123...json', '2025-11-26_conversation-with-456...json']
```

### 7. Convenience Method: Get by User, Guild, and Date
Retrieve a conversation by building the filename from user ID, guild ID, and date.

```python
from datetime import datetime

conversation_data = await services_manager.conversation_file_service_manager.get_conversation_by_user_and_guild_and_date(
    discord_user_id="123456789012345678",
    guild_id="987654321098765432",
    date=datetime(2025, 11, 25)  # Optional, defaults to today
)
```

## Integration with File Manager

The `ConversationFileManagerService` uses the base `FileManagerService` for all file operations, ensuring:

- **Atomic file writes**: Files are written to temporary files first, then atomically renamed
- **Thread-safe operations**: File locks prevent race conditions
- **Consistent error handling**: Standardized exceptions for common error cases
- **Absolute path handling**: Properly handles both absolute and relative paths

## Error Handling

The service provides clear error handling:

- **FileExistsError**: Raised when trying to save a conversation that already exists
- **FileNotFoundError**: Returned as `False` or `None` depending on the operation
- **RuntimeError**: Raised for unexpected file system errors with detailed context

## Design Patterns

### Following Existing Patterns

1. **Base Class Inheritance**: Inherits from `BaseConversationFileServiceManager`
2. **Service Lifecycle**: Implements `on_start()` and `on_close()` methods
3. **Logging Integration**: Uses the logging service for all operations
4. **Atomic Operations**: All file operations go through the `FileManagerService`
5. **Absolute Path Construction**: Builds absolute paths before passing to file_manager

### Key Differences from Other File Managers

Unlike `RecordingFileManagerService` which has temp/persistent storage, and `TranscriptionFileManagerService` which integrates with SQL, the `ConversationFileManagerService`:

- Uses **single-tier storage** (no temp/persistent separation)
- Is **file-only** (no SQL integration for basic operations)
- Focuses on **JSON conversation data** (messages and metadata)
- Uses **date-based filenames** (one file per user per guild per day)

## Usage Examples

### Complete Workflow Example

```python
# Initialize the service (automatically done during app startup)
conversation_manager = services_manager.conversation_file_service_manager

# Create a new conversation
conversation_data = {
    "messages": [
        {"role": "user", "content": "What's 2+2?"},
        {"role": "assistant", "content": "2 + 2 equals 4."}
    ],
    "metadata": {
        "created_at": datetime.now().isoformat(),
        "total_messages": 2
    }
}

# Save it
filename = await conversation_manager.save_conversation(
    conversation_data=conversation_data,
    discord_user_id="123456789012345678",
    guild_id="987654321098765432"
)

# Add more messages later
conversation_data["messages"].append({
    "role": "user", 
    "content": "And what's 3+3?"
})
conversation_data["messages"].append({
    "role": "assistant", 
    "content": "3 + 3 equals 6."
})
conversation_data["metadata"]["total_messages"] = 4

# Update the conversation
await conversation_manager.update_conversation(filename, conversation_data)

# Retrieve it later
retrieved = await conversation_manager.retrieve_conversation(filename)

# Or retrieve using the convenience method
retrieved = await conversation_manager.get_conversation_by_user_and_guild_and_date(
    discord_user_id="123456789012345678",
    guild_id="987654321098765432"
)

# Clean up old conversations
if await conversation_manager.conversation_exists(filename):
    await conversation_manager.delete_conversation(filename)
```

## Testing

Comprehensive unit tests are provided in:
```
tests/unit/services/test_conversation_file_manager.py
```

Run tests with:
```bash
pytest tests/unit/services/test_conversation_file_manager.py -v
```

## Future Enhancements

Potential improvements for future iterations:

1. **SQL Integration**: Add a companion SQL table to track conversation metadata
2. **Search Functionality**: Add methods to search conversations by date range or content
3. **Compression**: Implement automatic compression for older conversations
4. **Archive/Export**: Add methods to export conversations in different formats
5. **Conversation Compilation**: Merge multiple days of conversations into summaries
