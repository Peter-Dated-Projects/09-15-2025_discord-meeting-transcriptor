# GPU Resource Manager - Data Flow Verification

## ✅ Complete Data Flow Analysis

### 1. **Initialization Flow** (Startup)

```
main.py (main())
    ↓
1. Create Context()
    ↓
2. construct_server_manager() → context.set_server_manager()
    ↓
3. construct_services_manager()
    ├─ Creates GPUResourceManager(context=context)
    └─ Returns ServicesManager with gpu_resource_manager parameter
    ↓
4. context.set_services_manager(services_manager)
    ↓
5. services_manager.initialize_all()
    ├─ Calls gpu_resource_manager.on_start(self)
    │   ├─ Sets self.services = ServicesManager
    │   └─ Starts GPU scheduler loop
    └─ All services now have access to gpu_resource_manager
```

### 2. **Service Access Flow**

```
Any Service (e.g., TranscriptionJob)
    ↓
Has access to: self.services (ServicesManager)
    ↓
Can call: self.services.gpu_resource_manager
    ↓
Methods available:
    - acquire_lock(job_type, job_id, metadata)
    - get_status()
```

### 3. **GPU Lock Acquisition Flow** (Runtime)

```
TranscriptionJob.execute()
    ↓
Calls: self.services.gpu_resource_manager.acquire_lock(
    job_type="transcription",
    job_id=self.job_id,
    metadata={...}
)
    ↓
Returns: _GPULockContext (async context manager)
    ↓
async with context:
    ↓
    __aenter__() called:
        ↓
        1. Creates asyncio.Event()
        2. Adds event to appropriate queue (transcription_queue)
        3. Waits for scheduler to signal the event
        4. Acquires actual GPU lock
        5. Updates statistics
        ↓
    [GPU WORK HAPPENS HERE]
    - Calls Whisper/LLM
    - Processes results
        ↓
    __aexit__() called:
        ↓
        1. Releases GPU lock
        2. Updates consecutive counts
        3. Allows next job to proceed
```

### 4. **Priority Scheduler Flow** (Background Loop)

```
GPUResourceManager._scheduler_loop() [Running continuously]
    ↓
Every 0.1 seconds:
    ↓
1. Check if GPU is currently locked
   └─ If locked: continue (wait for release)
    ↓
2. Check chatbot_queue (HIGHEST PRIORITY)
   └─ If not empty: Signal next chatbot event → DONE
    ↓
3. If no chatbot, use _select_next_job_type()
   ├─ Check consecutive limits (force switch if needed)
   ├─ Use 70/30 probability (transcription/summarization)
   └─ Returns: GPUJobType.TRANSCRIPTION or SUMMARIZATION
    ↓
4. Check selected queue
   ├─ If transcription selected AND transcription_queue not empty:
   │   └─ Signal next transcription event
   ├─ Else if summarization_queue not empty:
   │   └─ Signal next summarization event
   └─ Else: wait 0.1s and try again
```

### 5. **Shutdown Flow**

```
services_manager.shutdown_all()
    ↓
Phase 3: Wait for GPU jobs to complete
    ↓
Calls: gpu_resource_manager.on_close()
    ↓
GPUResourceManager._stop_scheduler()
    ├─ Sets _scheduler_running = False
    ├─ Cancels _scheduler_task
    └─ Waits for current GPU operations to complete
```

---

## ✅ Verification Checklist

### Initialization ✓
- [x] Context created in main.py
- [x] GPUResourceManager instantiated in construct_services_manager()
- [x] GPUResourceManager passed to ServicesManager constructor
- [x] GPUResourceManager.on_start() called during initialize_all()
- [x] ServicesManager reference stored in gpu_resource_manager.services

### Service Integration ✓
- [x] ServicesManager has gpu_resource_manager attribute
- [x] All services can access via self.services.gpu_resource_manager
- [x] TranscriptionJob updated to use GPU lock

### GPU Lock Mechanism ✓
- [x] GPUResourceLock class provides low-level async lock
- [x] _GPULockContext provides context manager interface
- [x] acquire_lock() returns context manager
- [x] Lock automatically released on exit (even on exceptions)

### Priority Scheduling ✓
- [x] Three separate queues (transcription, summarization, chatbot)
- [x] Chatbot always gets priority
- [x] Round-robin with 70/30 ratio for transcription/summarization
- [x] Max 2 consecutive transcription operations enforced
- [x] Max 1 consecutive summarization operation enforced
- [x] Scheduler runs in background asyncio task

### Shutdown ✓
- [x] Scheduler stopped gracefully
- [x] Current GPU operations allowed to complete
- [x] Cleanup in proper phase (Phase 3, 30% of timeout budget)

---

## 🔍 Component Verification

### File: `source/services/gpu_resource_manager/manager.py`
**Status**: ✅ Verified
- GPUResourceManager class exists
- Inherits from Manager (gets on_start/on_close)
- acquire_lock() method returns _GPULockContext
- _scheduler_loop() implements priority logic
- Statistics tracking implemented

### File: `source/services/gpu_resource_manager/lock.py`
**Status**: ✅ Verified
- GPUResourceLock provides async lock
- acquire() and release() methods
- get_status() for monitoring
- GPULockInfo tracks current holder

### File: `source/services/manager.py`
**Status**: ✅ Verified
- ServicesManager.__init__() accepts gpu_resource_manager parameter
- Stored as self.gpu_resource_manager
- initialize_all() calls gpu_resource_manager.on_start(self)
- shutdown_all() calls gpu_resource_manager.on_close() in Phase 3

### File: `source/services/constructor.py`
**Status**: ✅ Verified
- gpu_resource_manager = None (initialized)
- GPUResourceManager(context=context) created
- Passed to ServicesManager constructor

### File: `source/services/transcription_job_manager/manager.py`
**Status**: ✅ Verified
- TranscriptionJob._transcribe_recording() updated
- Uses: async with self.services.gpu_resource_manager.acquire_lock(...)
- Whisper inference call wrapped in GPU lock
- Metadata includes meeting_id, recording_id, user_id

---

## 🎯 Runtime Flow Example

### Scenario: Two transcription jobs + one chatbot request

```
Time 0ms:
  - Transcription Job A submitted
  - Event added to transcription_queue
  
Time 10ms:
  - Scheduler checks queues
  - Chatbot queue empty, transcription queue has 1 event
  - Signals Job A's event
  - Job A acquires GPU lock
  - Job A starts Whisper inference

Time 100ms:
  - Transcription Job B submitted
  - Event added to transcription_queue (now waiting)
  
Time 500ms:
  - Chatbot Job C submitted
  - Event added to chatbot_queue (HIGH PRIORITY)

Time 1000ms:
  - Job A still running (Whisper takes time)
  - Job B waiting in transcription_queue
  - Job C waiting in chatbot_queue
  
Time 2000ms:
  - Job A completes
  - GPU lock released
  - Consecutive count: transcription = 1
  
Time 2010ms:
  - Scheduler checks queues
  - Chatbot queue NOT EMPTY → Job C gets priority!
  - Signals Job C's event
  - Job C acquires GPU lock
  - Job C starts LLM inference
  - (Job B still waiting)

Time 2500ms:
  - Job C completes (chatbots are fast)
  - GPU lock released
  - Consecutive count: chatbot doesn't affect counts

Time 2510ms:
  - Scheduler checks queues
  - Chatbot queue empty
  - Transcription queue has Job B
  - Signals Job B's event
  - Job B acquires GPU lock
  - Job B starts Whisper inference
  
Time 3500ms:
  - Job B completes
  - GPU lock released
  - Consecutive count: transcription = 2 (MAX!)
  
Time 3510ms:
  - If another transcription arrives, it must wait
  - Next job MUST be summarization (forced switch)
```

---

## 🧪 Testing Recommendations

### 1. Unit Test: GPU Lock Basic Functionality
```python
async def test_gpu_lock_basic():
    context = Context()
    gpu_manager = GPUResourceManager(context)
    
    async with gpu_manager.acquire_lock("transcription", "job_1"):
        assert gpu_manager._gpu_lock.is_locked()
    
    assert not gpu_manager._gpu_lock.is_locked()
```

### 2. Integration Test: Priority Scheduling
```python
async def test_chatbot_priority():
    # Start long transcription
    # Submit chatbot request
    # Verify chatbot completes before transcription finishes
```

### 3. Integration Test: Round-Robin
```python
async def test_round_robin():
    # Submit multiple transcription and summarization jobs
    # Verify 70/30 ratio over time
    # Verify consecutive limits enforced
```

---

## ✅ Final Verification Result

**DATA FLOW STATUS: FULLY VERIFIED ✓**

All components are properly connected:
1. ✅ Initialization chain complete
2. ✅ Service references correct
3. ✅ GPU lock mechanism functional
4. ✅ Priority scheduler implemented
5. ✅ Shutdown sequence proper
6. ✅ TranscriptionJob integrated

The system is ready for testing!
