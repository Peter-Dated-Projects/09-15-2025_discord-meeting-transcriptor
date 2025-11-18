# GPU Resource Manager Usage Guide

## Overview

The GPU Resource Manager provides a **centralized lock system** for managing GPU resources across different job types. It ensures only one GPU operation runs at a time, with intelligent priority-based scheduling.

## Key Features

1. **Single GPU Lock**: Only one job can use the GPU at a time
2. **Priority Scheduling**:
   - Chatbot requests: Always highest priority
   - Transcription/Summarization: Round-robin with 70/30 ratio
   - Max 2 consecutive transcription operations
   - Max 1 consecutive summarization operation
3. **Async Context Manager**: Clean lock acquisition/release pattern

## Usage

### Basic Pattern

```python
# In any job that needs GPU access
async def execute(self):
    # Acquire GPU lock with job type
    async with self.services.gpu_resource_manager.acquire_lock(
        job_type="transcription",  # or "summarization" or "chatbot"
        job_id=self.job_id,
        metadata={"meeting_id": self.meeting_id}
    ):
        # Do GPU work here - only this code has GPU access
        result = await self.services.server.whisper_server_client.inference(...)
        # Process result
```

### Example: Transcription Job

```python
async def _transcribe_recording(self, recording_id: str) -> None:
    """Transcribe a single recording file using GPU."""
    
    # Get recording info
    recording = await self.services.sql_recording_service_manager.get_recording_by_id(recording_id)
    audio_file_path = os.path.join(storage_path, recording["filename"])
    
    # Acquire GPU lock before calling Whisper
    async with self.services.gpu_resource_manager.acquire_lock(
        job_type="transcription",
        job_id=self.job_id,
        metadata={
            "meeting_id": self.meeting_id,
            "recording_id": recording_id,
            "user_id": recording["user_id"]
        }
    ):
        # GPU is locked - call Whisper
        transcript_text = await self.services.server.whisper_server_client.inference(
            audio_path=audio_file_path,
            word_timestamps=True,
            response_format="verbose_json",
            temperature="0.0",
            temperature_inc="0.2",
            language="en",
        )
        
        # GPU is still locked - save results
        await self._save_transcription(transcript_text, recording_id)
    
    # GPU lock automatically released here
    await self.services.logging_service.info(f"GPU released after transcription {recording_id}")
```

### Example: Summarization Job

```python
async def execute(self):
    """Generate summary using LLM on GPU."""
    
    # Acquire GPU lock
    async with self.services.gpu_resource_manager.acquire_lock(
        job_type="summarization",
        job_id=self.job_id,
        metadata={"summary_type": "meeting"}
    ):
        # Call LLM service (Ollama, etc.)
        summary = await self.services.server.ollama_client.generate(
            model="llama3.2",
            prompt=self.text_content,
            max_tokens=1000,
        )
        
        # Save summary
        self.metadata["summary"] = summary
    
    # GPU automatically released
```

### Example: Chatbot Request (High Priority)

```python
async def process_chatbot_query(self, user_message: str):
    """Process chatbot query with highest priority."""
    
    # Chatbot requests ALWAYS get priority
    async with self.services.gpu_resource_manager.acquire_lock(
        job_type="chatbot",  # This will interrupt transcription/summarization
        job_id=generate_16_char_uuid(),
        metadata={"user_id": user_id}
    ):
        # Call LLM for chat response
        response = await self.services.server.ollama_client.chat(
            model="llama3.2",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": user_message}
            ],
        )
        
        return response
```

## Job Type Priorities

```
Priority Level 1 (Highest):  CHATBOT
                             ↓
Priority Level 2:            TRANSCRIPTION (70% chance)
                             SUMMARIZATION (30% chance)
                             
Round-robin rules:
- Max 2 consecutive transcription operations
- Max 1 consecutive summarization operation
- After limits hit, forced switch to other type
```

## Integration with Existing Jobs

### Modify TranscriptionJob

**File**: `source/services/transcription_job_manager/manager.py`

```python
# BEFORE (direct Whisper call):
transcript_text = await self.services.server.whisper_server_client.inference(
    audio_path=audio_file_path,
    word_timestamps=True,
    response_format="verbose_json",
    temperature="0.0",
    temperature_inc="0.2",
    language="en",
)

# AFTER (with GPU lock):
async with self.services.gpu_resource_manager.acquire_lock(
    job_type="transcription",
    job_id=self.job_id,
    metadata={"recording_id": recording_id}
):
    transcript_text = await self.services.server.whisper_server_client.inference(
        audio_path=audio_file_path,
        word_timestamps=True,
        response_format="verbose_json",
        temperature="0.0",
        temperature_inc="0.2",
        language="en",
    )
```

## Monitoring

### Get GPU Status

```python
# Get current GPU status
status = services.gpu_resource_manager.get_status()

# Returns:
{
    "scheduler_running": True,
    "gpu_lock": {
        "is_locked": True,
        "current_holder": {
            "job_id": "abc123",
            "job_type": "transcription",
            "acquired_at": "2025-11-17T10:30:00",
            "metadata": {"recording_id": "rec_001"}
        },
        "wait_count": 3
    },
    "queue_sizes": {
        "transcription": 2,
        "summarization": 1,
        "chatbot": 0
    },
    "stats": {
        "total_transcription_locks": 10,
        "total_summarization_locks": 3,
        "total_chatbot_locks": 5,
        "consecutive_transcription": 1,
        "consecutive_summarization": 0,
        "last_job_type": "transcription"
    }
}
```

## Error Handling

```python
try:
    async with self.services.gpu_resource_manager.acquire_lock(
        job_type="transcription",
        job_id=self.job_id
    ):
        # GPU work
        result = await gpu_intensive_operation()
        
except Exception as e:
    # GPU lock is automatically released even on error
    await self.services.logging_service.error(f"GPU operation failed: {e}")
    raise
```

## Best Practices

1. **Keep GPU operations minimal**: Only wrap the actual GPU work in the lock
   ```python
   # ✅ GOOD - Only GPU work locked
   data = await prepare_data()  # No lock needed
   async with gpu_manager.acquire_lock("transcription"):
       result = await whisper_inference(data)  # GPU locked
   await save_result(result)  # No lock needed
   
   # ❌ BAD - Too much locked
   async with gpu_manager.acquire_lock("transcription"):
       data = await prepare_data()  # Doesn't need GPU!
       result = await whisper_inference(data)
       await save_result(result)  # Doesn't need GPU!
   ```

2. **Use appropriate job types**: This affects scheduling priority

3. **Include metadata**: Helps with debugging and monitoring

4. **Let the context manager handle cleanup**: Don't manually release locks

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│          GPU Resource Manager                            │
│                                                          │
│  ┌────────────────────────────────────────────────┐    │
│  │   Priority Scheduler                            │    │
│  │   - Chatbot: Priority 1                         │    │
│  │   - Transcription: 70% (max 2 consecutive)     │    │
│  │   - Summarization: 30% (max 1 consecutive)     │    │
│  └────────────────────────────────────────────────┘    │
│                      ↓                                   │
│  ┌────────────────────────────────────────────────┐    │
│  │   GPU Lock (Single Resource)                    │    │
│  │   - Only one holder at a time                   │    │
│  │   - Async acquire/release                       │    │
│  └────────────────────────────────────────────────┘    │
│                                                          │
└─────────────────────────────────────────────────────────┘
                       ↓
         ┌─────────────┼─────────────┐
         ↓             ↓              ↓
    Transcription   Summarization  Chatbot
       Jobs            Jobs          Jobs
         ↓             ↓              ↓
      Whisper         LLM            LLM
```

## Testing

```python
# Test basic lock acquisition
async def test_gpu_lock():
    async with services.gpu_resource_manager.acquire_lock("transcription"):
        print("GPU locked")
        await asyncio.sleep(1)
    print("GPU released")

# Test priority (chatbot interrupts transcription)
async def test_priority():
    # Start long transcription
    task1 = asyncio.create_task(long_transcription_job())
    
    await asyncio.sleep(0.5)
    
    # Start chatbot (should get priority)
    task2 = asyncio.create_task(chatbot_job())
    
    # Chatbot should complete before transcription
    await asyncio.gather(task1, task2)
```
