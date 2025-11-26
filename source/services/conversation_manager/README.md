# Conversation Manager Service

## Overview

The `InMemoryConversationManager` provides in-memory storage and management of ongoing conversations with the Echo Discord bot. It implements automatic cleanup of idle conversations after a configurable timeout period (default: 5 minutes).

## Purpose

This service is designed to:
- Store active conversations in memory for fast access
- Automatically clean up idle conversations to prevent memory leaks
- Provide easy integration with the `ConversationFileManagerService` for persistence
- Track conversation metadata including participants, timestamps, and message history

## Architecture

### Components

1. **MessageType Enum** - Defines the four types of messages:
   - `THINKING` - AI model thinking segments
   - `CHAT` - AI model text segments  
   - `TOOL_CALL` - Tool call requests
   - `TOOL_CALL_RESPONSE` - Tool call responses

2. **Message Class** - Represents a single message with:
   - Timestamp
   - Message type
   - Content
   - Optional tool call information
   - Optional requester information

3. **Conversation Class** - Represents a complete conversation with:
   - Thread ID (Discord thread)
   - Creation and update timestamps
   - Guild information
   - Participant list
   - Message history
   - Auto-generated filename for persistence

4. **InMemoryConversationManager** - Manages the lifecycle of conversations:
   - Creates and stores conversations
   - Schedules automatic cleanup after idle time
   - Provides access to active conversations
   - Handles persistence operations

## Usage

### Basic Setup

```python
from source.services.conversation_manager import InMemoryConversationManager

# Initialize with optional file manager for persistence
conversation_manager = InMemoryConversationManager(
    conversation_file_manager=services_manager.conversation_file_service_manager
)
```

### Creating a Conversation

```python
conversation = conversation_manager.create_conversation(
    thread_id="1234567890",
    guild_id="987654321",
    guild_name="My Discord Server",
    requester="123456789012345678"  # Discord user ID
)
```

### Adding Messages

```python
from datetime import datetime
from source.services.conversation_manager import Message, MessageType

# User message
user_message = Message(
    created_at=datetime.now(),
    message_type=MessageType.CHAT,
    message_content="Hello, Echo!",
    requester="123456789012345678"
)

conversation_manager.add_message_to_conversation(
    thread_id="1234567890",
    message=user_message
)

# AI thinking message
thinking_message = Message(
    created_at=datetime.now(),
    message_type=MessageType.THINKING,
    message_content="Let me process that request..."
)

conversation_manager.add_message_to_conversation(
    thread_id="1234567890",
    message=thinking_message
)

# AI response
response_message = Message(
    created_at=datetime.now(),
    message_type=MessageType.CHAT,
    message_content="Hi! How can I help you today?"
)

conversation_manager.add_message_to_conversation(
    thread_id="1234567890",
    message=response_message
)
```

### Tool Call Messages

```python
# Tool call request
tool_call_message = Message(
    created_at=datetime.now(),
    message_type=MessageType.TOOL_CALL,
    message_content="Calling search_documents tool",
    tools=[
        {
            "name": "search_documents",
            "params": {
                "query": "python async programming",
                "limit": 5
            }
        }
    ]
)

conversation_manager.add_message_to_conversation(
    thread_id="1234567890",
    message=tool_call_message
)

# Tool call response
tool_response_message = Message(
    created_at=datetime.now(),
    message_type=MessageType.TOOL_CALL_RESPONSE,
    message_content="Found 5 documents matching the query"
)

conversation_manager.add_message_to_conversation(
    thread_id="1234567890",
    message=tool_response_message
)
```

### Retrieving a Conversation

```python
conversation = conversation_manager.get_conversation(thread_id="1234567890")

if conversation:
    print(f"Conversation has {len(conversation.history)} messages")
    print(f"Participants: {conversation.participants}")
    print(f"Last updated: {conversation.updated_at}")
```

### Checking if a Thread has an Active Conversation

```python
# Check if a Discord thread has an active conversation
thread_id = str(message.channel.id)
if conversation_manager.is_conversation_thread(thread_id):
    print(f"Thread {thread_id} has an active conversation")
    # Handle message in existing conversation
else:
    print(f"Thread {thread_id} does not have an active conversation")
    # Create new conversation or ignore message
```

This is useful for:
- Filtering messages in Discord event handlers
- Determining if a message should be processed as part of an ongoing conversation
- Checking conversation state before performing actions

### Saving a Conversation to Disk

```python
# Save a specific conversation
conversation = conversation_manager.get_conversation(thread_id="1234567890")
if conversation:
    success = await conversation.save_conversation()
    print(f"Save {'successful' if success else 'failed'}")

# Save all active conversations
results = await conversation_manager.save_all_conversations()
for thread_id, success in results.items():
    print(f"Thread {thread_id}: {'saved' if success else 'failed'}")
```

### Manual Cleanup

```python
# Remove a conversation from memory immediately
conversation_manager.remove_conversation(thread_id="1234567890")

# Get all active conversations
all_conversations = conversation_manager.get_all_conversations()
print(f"Active conversations: {len(all_conversations)}")
```

### Graceful Shutdown

```python
# Cancel all cleanup tasks before shutting down
await conversation_manager.shutdown()
```

## Automatic Cleanup

The conversation manager automatically removes conversations from memory after they've been idle for `IDLE_TIME` (default: 5 minutes). The idle timer resets every time a message is added to the conversation.

```python
# Modify the idle time (in seconds)
InMemoryConversationManager.IDLE_TIME = 10 * 60  # 10 minutes
```

**Important Notes:**
- Conversations are NOT automatically saved to disk before cleanup
- If you need to preserve conversations, call `save_conversation()` explicitly
- Adding a message to a conversation resets its idle timer

## JSON Format

### Message JSON Format

```json
{
  "created_at": "2025-11-25T10:30:00.123456",
  "message_type": "chat",
  "message_content": "Hello, Echo!",
  "meta": {
    "requester": "123456789012345678"
  }
}
```

### Tool Call Message JSON Format

```json
{
  "created_at": "2025-11-25T10:30:05.123456",
  "message_type": "tool_call",
  "message_content": "Calling search_documents",
  "meta": {
    "tools": [
      {
        "name": "search_documents",
        "params": {
          "query": "python async",
          "limit": 5
        }
      }
    ]
  }
}
```

### Conversation JSON Format

```json
{
  "created_at": "2025-11-25T10:30:00.000000",
  "updated_at": "2025-11-25T10:35:00.000000",
  "summary": "User asked about async programming",
  "guild_id": "987654321",
  "guild_name": "My Discord Server",
  "requester": "123456789012345678",
  "participants": ["123456789012345678", "987654321012345678"],
  "history": [
    {
      "created_at": "2025-11-25T10:30:00.123456",
      "message_type": "chat",
      "message_content": "Hello, Echo!",
      "meta": {
        "requester": "123456789012345678"
      }
    },
    {
      "created_at": "2025-11-25T10:30:02.123456",
      "message_type": "thinking",
      "message_content": "Processing request...",
      "meta": {}
    },
    {
      "created_at": "2025-11-25T10:30:03.123456",
      "message_type": "chat",
      "message_content": "Hi! How can I help you?",
      "meta": {}
    }
  ]
}
```

## Integration with ConversationFileManager

The conversation manager integrates seamlessly with the `ConversationFileManagerService`:

```python
# Setup
conversation_manager = InMemoryConversationManager(
    conversation_file_manager=services_manager.conversation_file_service_manager
)

# Create conversation (filename is auto-generated)
conversation = conversation_manager.create_conversation(
    thread_id="1234567890",
    guild_id="987654321",
    guild_name="My Server",
    requester="123456789012345678"
)

# Filename format: yyyy-mm-dd_conversation-with-{user_id}-in-{guild_id}.json
print(conversation.filename)
# Output: 2025-11-25_conversation-with-123456789012345678-in-987654321.json

# Save to disk
await conversation.save_conversation()
```

## Error Handling

```python
# Conversation without file manager
conversation = Conversation(
    thread_id="123",
    created_at=datetime.now(),
    guild_id="456",
    guild_name="Test",
    requester="789"
)

try:
    await conversation.save_conversation()
except ValueError as e:
    print(f"Error: {e}")
    # Output: conversation_file_manager is not set. Cannot save conversation.
```

## Best Practices

1. **Always initialize with a file manager** if you plan to persist conversations
2. **Save important conversations** before they idle out (within 5 minutes of last activity)
3. **Call shutdown()** when your application closes to clean up async tasks
4. **Monitor memory usage** if dealing with many concurrent conversations
5. **Update conversation summaries** periodically for better organization
6. **Reset idle time** based on your use case (longer for production, shorter for testing)

## Thread Safety

**Note:** This implementation is NOT thread-safe. If you need to access conversations from multiple threads, you should add appropriate locking mechanisms.

## Future Enhancements

- [ ] Tool call extractor implementation (pending design)
- [ ] Automatic summary generation
- [ ] Conversation search and filtering
- [ ] Batch operations for multiple conversations
- [ ] Configurable cleanup strategies
- [ ] Thread-safe operations
- [ ] Metrics and monitoring
