# Architecture Overview

## System Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Discord Bot (Echo)                           │
│                                                                   │
│  User pings Echo → Thread Created → Conversation Started         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              InMemoryConversationManager                         │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  conversations: Dict[thread_id, Conversation]            │   │
│  │  cleanup_tasks: Dict[thread_id, asyncio.Task]           │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                   │
│  Methods:                                                         │
│  • create_conversation()                                          │
│  • get_conversation()                                             │
│  • add_message_to_conversation()                                 │
│  • remove_conversation()                                          │
└───────────────┬───────────────────────────────┬─────────────────┘
                │                               │
                │                               │
                ▼                               ▼
    ┌──────────────────────┐      ┌──────────────────────────┐
    │   Conversation        │      │   Cleanup Timer          │
    │                       │      │   (5 minutes)            │
    │ • thread_id           │      │                          │
    │ • created_at          │      │  After idle:             │
    │ • updated_at          │      │  → Remove from memory    │
    │ • guild_id/name       │      └──────────────────────────┘
    │ • requester           │
    │ • participants        │
    │ • history: [Message]  │
    │ • filename            │
    └───────┬───────────────┘
            │
            ▼
    ┌──────────────────────────────────────────────────┐
    │              Message Objects                      │
    │                                                   │
    │  ┌──────────────┐  ┌──────────────┐             │
    │  │  THINKING    │  │    CHAT      │             │
    │  └──────────────┘  └──────────────┘             │
    │                                                   │
    │  ┌──────────────┐  ┌──────────────────────────┐ │
    │  │  TOOL_CALL   │  │ TOOL_CALL_RESPONSE       │ │
    │  └──────────────┘  └──────────────────────────┘ │
    └───────────────────────────────────────────────────┘
```

## Data Flow

### 1. Conversation Creation
```
User Message
    │
    ├─> InMemoryConversationManager.create_conversation()
    │
    ├─> Create Conversation object
    │   • Auto-generate filename
    │   • Initialize participants list
    │   • Set created_at timestamp
    │
    ├─> Store in conversations dict
    │   conversations[thread_id] = conversation
    │
    └─> Schedule cleanup after 5 minutes
        cleanup_tasks[thread_id] = asyncio.Task
```

### 2. Adding Messages
```
New Message
    │
    ├─> InMemoryConversationManager.add_message_to_conversation()
    │
    ├─> Get conversation from dict
    │
    ├─> Conversation.add_message()
    │   • Append to history
    │   • Update updated_at timestamp
    │   • Add to participants if new user
    │
    ├─> Cancel existing cleanup task
    │
    └─> Schedule new cleanup (reset 5-minute timer)
```

### 3. Automatic Cleanup
```
Idle Timer (5 minutes)
    │
    ├─> asyncio.sleep(IDLE_TIME)
    │
    ├─> Remove from conversations dict
    │   del conversations[thread_id]
    │
    └─> Remove cleanup task
        del cleanup_tasks[thread_id]

Note: Conversation NOT saved to disk automatically
```

### 4. Manual Save
```
Save Request
    │
    ├─> Conversation.save_conversation()
    │
    ├─> Convert to JSON
    │   conversation.to_json()
    │
    ├─> Check if file exists
    │   conversation_file_manager.conversation_exists()
    │
    ├─> If exists:
    │   └─> Update existing
    │       conversation_file_manager.update_conversation()
    │
    └─> If new:
        └─> Save new
            conversation_file_manager.save_conversation()
```

## Object Relationships

```
InMemoryConversationManager
    │
    ├─── conversations: Dict
    │       │
    │       └─── [thread_id] → Conversation
    │                              │
    │                              ├─── history: List
    │                              │       │
    │                              │       ├─── Message (THINKING)
    │                              │       ├─── Message (CHAT)
    │                              │       ├─── Message (TOOL_CALL)
    │                              │       └─── Message (TOOL_CALL_RESPONSE)
    │                              │
    │                              ├─── participants: List[str]
    │                              ├─── guild_id: str
    │                              └─── conversation_file_manager
    │
    └─── cleanup_tasks: Dict
            │
            └─── [thread_id] → asyncio.Task
                                   │
                                   └─── _cleanup_after_idle()
```

## Message Type Usage

### THINKING
```python
Message(
    message_type=MessageType.THINKING,
    message_content="Let me analyze your request...",
    # No requester or tools
)
```

### CHAT
```python
# User message
Message(
    message_type=MessageType.CHAT,
    message_content="Hello, Echo!",
    requester="123456789"  # Discord user ID
)

# AI response
Message(
    message_type=MessageType.CHAT,
    message_content="Hi! How can I help?",
    # No requester
)
```

### TOOL_CALL
```python
Message(
    message_type=MessageType.TOOL_CALL,
    message_content="Searching documentation",
    tools=[
        {
            "name": "search_docs",
            "params": {
                "query": "python async",
                "limit": 5
            }
        }
    ]
)
```

### TOOL_CALL_RESPONSE
```python
Message(
    message_type=MessageType.TOOL_CALL_RESPONSE,
    message_content="Found 5 relevant documents",
    # No requester or tools
)
```

## Lifecycle States

```
┌──────────────┐
│   CREATED    │  ← create_conversation()
└──────┬───────┘
       │
       ▼
┌──────────────┐
│    ACTIVE    │  ← add_message_to_conversation()
└──────┬───────┘    (resets idle timer)
       │
       ├─────────────────────────┐
       │                         │
       ▼                         ▼
┌──────────────┐         ┌──────────────┐
│  IDLE (5min) │         │    SAVED     │ ← save_conversation()
└──────┬───────┘         └──────┬───────┘
       │                         │
       ▼                         │
┌──────────────┐                 │
│   REMOVED    │ ← remove_conversation()
└──────────────┘                 │
       ▲                         │
       └─────────────────────────┘
```

## Integration with File Manager

```
InMemoryConversationManager
    │
    │ (reference)
    ├────────────────────────────────┐
    │                                │
    ▼                                ▼
Conversation                  ConversationFileManager
    │                                │
    │ save_conversation()            │
    ├────────────────────────────────┤
    │                                │
    │ 1. to_json()                   │
    │                                │
    │ 2. conversation_exists()  ────►│
    │    ◄─────────────────────── bool
    │                                │
    │ 3a. If new:                    │
    │     save_conversation()   ────►│
    │                                │
    │ 3b. If exists:                 │
    │     update_conversation() ────►│
    │                                │
    └────────────────────────────────┘

Filename auto-generated:
yyyy-mm-dd_conversation-with-{user_id}-in-{guild_id}.json
```

## Performance Considerations

### Memory Usage
- **Per Message**: ~500 bytes (text + metadata)
- **Per Conversation**: ~1-5 KB (depends on message count)
- **100 Active Conversations**: ~500 KB - 2.5 MB

### Cleanup Overhead
- Each conversation has 1 asyncio task
- Task sleeps for 5 minutes (no CPU usage)
- Cleanup is instant (dict deletion)

### Concurrency
- Not thread-safe (use from single async event loop)
- All operations are O(1) dict lookups
- No blocking operations in memory operations

## Error Handling

```
┌──────────────────────────────────────┐
│  save_conversation()                 │
│                                      │
│  ├─ No file_manager set              │
│  │  → ValueError                     │
│  │                                   │
│  ├─ File operation fails             │
│  │  → Returns False                  │
│  │  → Exception caught & logged      │
│  │                                   │
│  └─ Success                          │
│     → Returns True                   │
└──────────────────────────────────────┘
```

## Best Practices

1. **Initialize with file manager**
   ```python
   manager = InMemoryConversationManager(
       conversation_file_manager=file_manager
   )
   ```

2. **Save before idle timeout**
   ```python
   if important:
       await conversation.save_conversation()
   ```

3. **Cleanup on shutdown**
   ```python
   await manager.shutdown()
   ```

4. **Handle missing conversations**
   ```python
   conv = manager.get_conversation(thread_id)
   if conv is None:
       # Create new or handle error
   ```

5. **Batch operations**
   ```python
   # Save all before shutdown
   results = await manager.save_all_conversations()
   ```
