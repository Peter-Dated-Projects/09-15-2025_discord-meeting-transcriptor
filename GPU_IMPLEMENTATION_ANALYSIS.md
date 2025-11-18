# GPU Resource Manager Implementation Analysis

## Current Architecture Understanding

### Existing Job Manager Pattern (TranscriptionJobManager)
1. **Job Creation Flow**:
   - Jobs are created by other services (e.g., `SQLRecordingManagerService`)
   - Jobs are queued using `create_and_queue_transcription_job()`
   - Each job has SQL tracking for status/history
   
2. **Job Processing**:
   - Uses `JobQueue` with callbacks (`on_job_started`, `on_job_complete`, `on_job_failed`)
   - Jobs directly call GPU services in their `execute()` method
   - Currently **NO GPU resource management** - transcription jobs directly call Whisper

3. **Service Initialization**:
   - Managers are created in `construct_services_manager()`
   - Added to `ServicesManager` constructor
   - Initialized in `ServicesManager.initialize_all()`
   - Shut down in `ServicesManager.shutdown_all()`

## Proposed Implementation Approaches

### **Approach 1: GPU Manager as Central Coordinator (RECOMMENDED)**

This approach treats the GPU manager as a **meta-queue** that coordinates all GPU work.

#### Architecture:
```
User Request → Service Manager → GPU Resource Manager → GPU Job Queue → GPU Work
                                        ↓
                              Priority Scheduler
                        (Chatbot > Transcription/Summarization)
```

#### Key Changes:
1. **Modify Existing TranscriptionJobManager**:
   - Instead of directly calling Whisper, submit jobs to GPU Resource Manager
   - Example:
     ```python
     # OLD: Direct Whisper call
     transcript = await self.services.server.whisper_server_client.inference(...)
     
     # NEW: Submit to GPU Manager
     gpu_job = TranscriptionJob(
         job_id=generate_16_char_uuid(),
         audio_file_path=audio_file_path,
         meeting_id=self.meeting_id,
         recording_id=recording_id,
         user_id=user_id,
         services=self.services
     )
     await self.services.gpu_resource_manager.submit_transcription_job(gpu_job)
     ```

2. **Create New Services for Summarization/Chatbot**:
   - `SummarizationJobManager` - manages summarization requests
   - `ChatbotJobManager` - manages chatbot queries
   - Both submit to GPU Resource Manager

3. **GPU Manager Responsibilities**:
   - Maintain 3 separate queues (transcription, summarization, chatbot)
   - Implement priority scheduler with round-robin logic
   - Acquire/release GPU lock automatically in callbacks
   - Return job status/results to original requesters

#### Pros:
- ✅ Centralized GPU resource control
- ✅ Clear separation of concerns
- ✅ Easy to monitor/debug GPU usage
- ✅ Prevents GPU conflicts between job types
- ✅ Existing jobs can gradually migrate to GPU manager

#### Cons:
- ⚠️ Additional layer of indirection
- ⚠️ Need to modify existing transcription job flow
- ⚠️ Job tracking becomes more complex (original job + GPU job)

---

### **Approach 2: GPU Manager as Resource Lock Only (Lightweight)**

This approach keeps existing job managers but adds GPU locking.

#### Architecture:
```
User Request → Transcription Job Manager → Acquire GPU Lock → Whisper
User Request → Summarization Job Manager → Acquire GPU Lock → LLM
User Request → Chatbot Job Manager → Acquire GPU Lock → LLM
```

#### Key Changes:
1. **GPU Manager provides lock interface**:
   ```python
   async with self.services.gpu_resource_manager.acquire_gpu_lock(job_type="transcription"):
       # Do GPU work
       transcript = await self.services.server.whisper_server_client.inference(...)
   ```

2. **Each job manager implements its own queue**:
   - TranscriptionJobManager keeps its existing queue
   - New SummarizationJobManager with its own queue
   - New ChatbotJobManager with its own queue

3. **GPU Manager only handles**:
   - Single GPU lock
   - Priority logic (chatbot > others)
   - Round-robin scheduler for non-chatbot jobs

#### Pros:
- ✅ Minimal changes to existing code
- ✅ Each manager maintains independence
- ✅ Simpler job tracking (one job per manager)

#### Cons:
- ❌ **Cannot implement true priority scheduling** - once a transcription job starts, it holds the lock
- ❌ No central visibility into GPU usage
- ❌ Hard to enforce "max 2 transcription jobs" rule
- ❌ Chatbot jobs must wait for current job to finish (violates priority requirement)

---

### **Approach 3: Hybrid - GPU Manager + Smart Forwarding**

Combines both approaches: central coordination with delegation.

#### Architecture:
```
User Request → Service Manager → GPU Resource Manager
                                        ↓
                              [Priority Scheduler]
                                        ↓
                    ┌─────────────┬─────────────┬─────────────┐
                    ↓             ↓             ↓
            Transcription   Summarization   Chatbot
            Job Executor    Job Executor    Job Executor
```

#### Key Changes:
1. **GPU Manager receives ALL GPU job requests**:
   ```python
   # From anywhere in the app
   job_id = await services.gpu_resource_manager.submit_transcription_job(
       audio_path="...",
       meeting_id="...",
       ...
   )
   ```

2. **GPU Manager maintains queues + executors**:
   - Three queues for job types
   - Priority scheduler selects next job
   - Delegates to specialized executors that hold business logic

3. **Executors are lightweight**:
   - `TranscriptionJobExecutor` - just the Whisper call + file saving
   - `SummarizationJobExecutor` - just the LLM call + result storage
   - `ChatbotJobExecutor` - just the LLM call + response formatting

#### Pros:
- ✅ True priority scheduling
- ✅ Central GPU management
- ✅ Business logic separated from coordination
- ✅ Easy to add new GPU job types

#### Cons:
- ⚠️ More refactoring required
- ⚠️ Need to create executor abstractions

---

## Recommended Implementation: **Approach 1** 

### Rationale:
1. **Meets all requirements**:
   - ✅ Single GPU lock with proper acquire/release
   - ✅ Three separate queues (transcription, summarization, chatbot)
   - ✅ Priority scheduling (chatbot always first)
   - ✅ Round-robin with 70/30 ratio
   - ✅ Max consecutive job limits

2. **Minimal disruption**:
   - Can keep existing `TranscriptionJobManager` structure
   - Just change where jobs are submitted (to GPU manager instead of direct Whisper)
   - Gradual migration path

3. **Best for long-term maintenance**:
   - All GPU coordination in one place
   - Easy to add new GPU job types
   - Clear monitoring and debugging

### Implementation Steps:

1. ✅ **Already Done**:
   - Created GPU resource manager with lock system
   - Created job types (TranscriptionJob, SummarizationJob, ChatbotJob)
   - Created priority scheduler with round-robin

2. **Next Steps**:
   - Add GPU Resource Manager to `construct_services_manager()`
   - Wire up GPU manager in `ServicesManager` initialization
   - Modify existing `TranscriptionJobManager` to use GPU manager
   - Create simple `SummarizationJobManager` and `ChatbotJobManager`
   - Update shutdown sequence to wait for GPU jobs

3. **Testing Strategy**:
   - Test transcription job submission through GPU manager
   - Test priority: chatbot interrupts transcription/summarization
   - Test round-robin: verify 70/30 ratio over time
   - Test consecutive limits: max 2 transcription, max 1 summarization
   - Test GPU lock: verify only one job runs at a time

---

## Key Design Decisions

### Job Lifecycle:
```
1. Service creates job → submits to GPU manager
2. GPU manager queues job (by type)
3. Scheduler selects next job based on priority
4. Acquire GPU lock
5. Execute job (call Whisper/LLM)
6. Release GPU lock
7. Callback to original service (if needed)
```

### Job Status Tracking:
- **Option A**: GPU manager tracks all GPU jobs in its own tables
- **Option B**: Original service tracks job, GPU manager just executes
- **Recommended**: Option B - let TranscriptionJobManager track transcription jobs, GPU manager just handles execution

### Error Handling:
- GPU job failure → release lock immediately
- Retry logic → handled by individual JobQueues
- GPU lock timeout → add timeout parameter to avoid infinite waits

---

## Migration Path

### Phase 1 (Current):
- GPU Resource Manager exists but not integrated
- Existing transcription jobs bypass GPU manager

### Phase 2 (Next):
- Wire GPU manager into ServicesManager
- Keep existing transcription flow as-is (compatibility)

### Phase 3 (Migration):
- Add flag to use GPU manager for transcriptions
- Test in development environment

### Phase 4 (Full Adoption):
- All GPU work goes through GPU manager
- Remove direct Whisper/LLM calls from other services
- Add summarization and chatbot job managers
