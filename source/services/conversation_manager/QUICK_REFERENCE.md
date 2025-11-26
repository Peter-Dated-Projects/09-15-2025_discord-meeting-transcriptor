# Quick Reference Guide

## 🚀 Quick Start

```python
from source.services.conversation_manager import (
    InMemoryConversationManager,
    Message,
    MessageType,
)
from datetime import datetime

# Initialize
manager = InMemoryConversationManager(
    conversation_file_manager=services_manager.conversation_file_service_manager
)

# Create conversation
conv = manager.create_conversation(
    thread_id="123",
    guild_id="456",
    guild_name="My Server",
    requester="789"
)

# Add message
msg = Message(
    created_at=datetime.now(),
    message_type=MessageType.CHAT,
    message_content="Hello!",
    requester="789"
)
manager.add_message_to_conversation("123", msg)

# Save (optional - not automatic!)
await conv.save_conversation()

# Cleanup on shutdown
await manager.shutdown()
```

## 📋 Checklist: Requirements Met

### Message Object ✅
- [x] 4 message type enums (THINKING, CHAT, TOOL_CALL, TOOL_CALL_RESPONSE)
- [x] Store thinking segments
- [x] Store chat segments  
- [x] Store tool call requests
- [x] Store tool call responses
- [x] JSONable with specified format
- [x] `created_at` timestamp
- [x] `message_type` as enum string
- [x] `message_content` field
- [x] `meta.tools` for tool calls
- [x] `meta.requester` for user messages

### Conversation Object ✅
- [x] Store conversation metadata
- [x] `created_at` timestamp
- [x] `updated_at` timestamp
- [x] `summary` string field
- [x] `guild_id` field
- [x] `guild_name` field
- [x] `requester` field (original requester)
- [x] `participants` list (all users)
- [x] `history` list of messages
- [x] JSONable with specified format
- [x] Auto-generated filename variable
- [x] `save_conversation()` method
- [x] Integration with conversation_file_manager

### Conversation Manager ✅
- [x] `IDLE_TIME` constant = 5 minutes (300 seconds)
- [x] Store conversations in dict (thread_id -> Conversation)
- [x] Create conversations when user pings Echo
- [x] Automatic cleanup after 5 minutes idle
- [x] Clear conversation from memory (no disk save)
- [x] Reset idle timer on message add

## 🎯 Core Methods

| Method | Purpose |
|--------|---------|
| `create_conversation()` | Create new conversation in memory |
| `get_conversation()` | Retrieve by thread_id |
| `is_conversation_thread()` | Check if thread has active conversation |
| `add_message_to_conversation()` | Add message & reset timer |
| `remove_conversation()` | Manual removal |
| `get_all_conversations()` | Get all active |
| `save_all_conversations()` | Save all to disk |
| `shutdown()` | Cancel cleanup tasks |

## 📦 Files Created

```
source/services/conversation_manager/
├── __init__.py                    # Module exports
├── in_memory_cache.py            # Core implementation
├── README.md                     # Comprehensive documentation
├── ARCHITECTURE.md               # System design & diagrams
├── IMPLEMENTATION_SUMMARY.md     # What was built
├── QUICK_REFERENCE.md           # This file
├── example_usage.py              # Working examples
└── test_in_memory_cache.py      # Unit tests
```

## 🔑 Key Features

### Auto-Generated Filenames
```
Format: yyyy-mm-dd_conversation-with-{user_id}-in-{guild_id}.json
Example: 2025-11-25_conversation-with-123456789-in-987654321.json
```

### Automatic Participant Tracking
```python
# Requester automatically added
conv = manager.create_conversation(requester="111", ...)
# conv.participants = ["111"]

# New participants automatically tracked
msg = Message(requester="222", ...)
conv.add_message(msg)
# conv.participants = ["111", "222"]
```

### Idle Timer Reset
```python
# Timer starts at conversation creation
conv = manager.create_conversation(...)  # T=0, cleanup at T=5min

# Adding message resets timer
manager.add_message_to_conversation(...)  # T=3min, cleanup now at T=8min
```

## ⚠️ Important Notes

1. **NOT Automatically Saved**: Conversations are removed from memory after 5 minutes without saving to disk. Call `save_conversation()` explicitly if needed.

2. **NOT Thread-Safe**: Use from a single async event loop only.

3. **Tool Call Extraction**: Intentionally NOT implemented per your instructions (design pending).

4. **Cleanup on Shutdown**: Always call `manager.shutdown()` to cancel async tasks.

## 🧪 Testing

```bash
# Run unit tests
pytest source/services/conversation_manager/test_in_memory_cache.py

# Run examples
python source/services/conversation_manager/example_usage.py
```

## 📝 JSON Formats

### Message
```json
{
  "created_at": "2025-11-25T10:30:00.000000",
  "message_type": "chat",
  "message_content": "Hello!",
  "meta": {
    "requester": "123456789"
  }
}
```

### Tool Call
```json
{
  "created_at": "2025-11-25T10:30:00.000000",
  "message_type": "tool_call",
  "message_content": "Searching...",
  "meta": {
    "tools": [
      {
        "name": "search_docs",
        "params": {"query": "python", "limit": 5}
      }
    ]
  }
}
```

### Conversation
```json
{
  "created_at": "2025-11-25T10:30:00.000000",
  "updated_at": "2025-11-25T10:35:00.000000",
  "summary": "Discussion about Python",
  "guild_id": "987654321",
  "guild_name": "My Server",
  "requester": "123456789",
  "participants": ["123456789", "987654321"],
  "history": [...]
}
```

## 🔗 Integration Points

### With ConversationFileManager
```python
# Set during initialization
manager = InMemoryConversationManager(
    conversation_file_manager=file_manager_service
)

# Used in save operations
await conversation.save_conversation()
```

### With Discord Bot
```python
# When user pings Echo in a thread
@bot.event
async def on_message(message):
    if bot_mentioned(message):
        # Create or get conversation
        conv = manager.get_conversation(str(message.channel.id))
        if not conv:
            conv = manager.create_conversation(
                thread_id=str(message.channel.id),
                guild_id=str(message.guild.id),
                guild_name=message.guild.name,
                requester=str(message.author.id)
            )
        
        # Add user message
        user_msg = Message(
            created_at=datetime.now(),
            message_type=MessageType.CHAT,
            message_content=message.content,
            requester=str(message.author.id)
        )
        manager.add_message_to_conversation(
            str(message.channel.id),
            user_msg
        )
        
        # ... process and respond ...
```

### Thread-based Message Filtering
```python
# Filter messages to check if they're in conversation threads
@bot.event
async def on_message(message):
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Check if message is in a thread with active conversation
    if isinstance(message.channel, discord.Thread):
        thread_id = str(message.channel.id)
        if manager.is_conversation_thread(thread_id):
            # Message is in an active conversation thread
            # Handle it even without bot mention
            await handle_conversation_message(message, thread_id)
            return
    
    # Otherwise, check for bot mention to start new conversation
    if bot.user in message.mentions:
        await start_new_conversation(message)
```

This pattern allows conversations to continue naturally in threads without requiring
users to mention the bot in every message.

## 🎨 Message Type Patterns

```python
# User request
Message(MessageType.CHAT, "Hello!", requester="123")

# AI thinking
Message(MessageType.THINKING, "Processing...")

# AI response  
Message(MessageType.CHAT, "Here's the answer...")

# Tool call
Message(
    MessageType.TOOL_CALL,
    "Calling search",
    tools=[{"name": "search", "params": {...}}]
)

# Tool result
Message(MessageType.TOOL_CALL_RESPONSE, "Found 5 results")
```

## 🛠️ Configuration

```python
# Change idle time (default: 5 minutes)
InMemoryConversationManager.IDLE_TIME = 10 * 60  # 10 minutes

# Per-instance configuration
manager = InMemoryConversationManager(
    conversation_file_manager=file_manager  # Optional
)
```

## 📚 Documentation Files

1. **README.md** - Full usage guide with examples
2. **ARCHITECTURE.md** - System design & flow diagrams  
3. **IMPLEMENTATION_SUMMARY.md** - What was built
4. **QUICK_REFERENCE.md** - This file (quick lookup)

## 🐛 Common Issues

### ValueError: conversation_file_manager is not set
```python
# ❌ Wrong
conv = Conversation(...)
await conv.save_conversation()  # Error!

# ✅ Correct
manager = InMemoryConversationManager(
    conversation_file_manager=file_manager
)
conv = manager.create_conversation(...)
await conv.save_conversation()  # Works!
```

### Conversation disappears
```python
# Conversations auto-cleanup after 5 minutes
# Save before timeout if needed
conv = manager.get_conversation(thread_id)
if conv and important:
    await conv.save_conversation()
```

### Can't find conversation
```python
# Always check if conversation exists
conv = manager.get_conversation(thread_id)
if conv is None:
    # Create new or handle appropriately
    conv = manager.create_conversation(...)
```

## 🎯 Next Steps

1. Integrate into bot's cog system
2. Hook up to message events
3. Add logging integration
4. Implement summary generation
5. Design & implement tool call extraction
6. Add metrics/monitoring
7. Consider adding to ServicesManager

## 📞 Support

See full documentation in:
- `README.md` for comprehensive usage
- `ARCHITECTURE.md` for system design
- `example_usage.py` for working examples
- `test_in_memory_cache.py` for test patterns
