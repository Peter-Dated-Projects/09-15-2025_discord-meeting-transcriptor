# Ollama Request Manager

A comprehensive wrapper around the Ollama API with full configuration support, conversation history management, streaming, and retry logic.

## Features

- ✅ **Full Chat History Management** - Session-based conversation tracking with automatic truncation
- ✅ **Configurable Generation Parameters** - Temperature, top_p, top_k, repeat_penalty, etc.
- ✅ **Streaming & Non-Streaming** - Support for both modes with unified interface
- ✅ **Retry Logic** - Automatic retry with exponential backoff
- ✅ **JSON Output Mode** - Force JSON-formatted responses
- ✅ **Keep-Alive Management** - Control model memory persistence
- ✅ **Request Metadata** - Track and log custom metadata
- ✅ **Session Management** - Create, retrieve, and delete conversation sessions
- ✅ **Usage Statistics** - Track requests, tokens, errors, and model usage
- ✅ **Future-Proof** - Hooks for RAG, function-calling, and tool use

## Installation

The manager requires the `ollama` Python package:

```bash
pip install ollama>=0.6.0
```

## Quick Start

### Basic Usage

```python
from source.services.ollama_request_manager import OllamaRequestManager

# Initialize manager
manager = OllamaRequestManager(
    context=context,
    host="http://localhost:11434",
    default_model="llama2"
)
await manager.on_start(services)

# Simple query
result = await manager.query(
    model="llama2",
    prompt="What is the capital of France?"
)
print(result.content)  # "Paris is the capital of France."
```

### Session-Based Conversations

```python
# Start a conversation
result = await manager.query(
    model="llama2",
    prompt="Tell me about Python",
    session_id="user_123"
)

# Continue the conversation (history is automatic)
result = await manager.query(
    model="llama2",
    prompt="What are its main features?",
    session_id="user_123"
)

# The manager remembers the context automatically
```

### Streaming Responses

```python
# Stream a long response
async for chunk in await manager.query(
    model="llama2",
    prompt="Tell me a long story about space exploration",
    stream=True
):
    print(chunk, end="")
```

### Advanced Configuration

```python
result = await manager.query(
    model="llama2",
    prompt="Generate a creative story",
    temperature=0.9,        # Higher creativity
    top_p=0.95,
    top_k=50,
    num_predict=500,        # Max 500 tokens
    repeat_penalty=1.2,
    stop=["END", "\n\n"],  # Stop sequences
    system_prompt="You are a creative storyteller",
    metadata={"user_id": "123", "task": "story_generation"}
)
```

### JSON Output Mode

```python
result = await manager.query(
    model="llama2",
    prompt="Give me a JSON object with name, age, and city",
    format="json"
)
# Response will be valid JSON
```

## API Reference

### OllamaRequestManager

#### Constructor

```python
OllamaRequestManager(
    context: Context,
    host: str = "http://localhost:11434",
    default_model: str = "llama2",
    default_system_prompt: str | None = None,
    max_history_length: int = 50,
    max_history_tokens: int | None = None,
)
```

**Parameters:**
- `context`: Application context
- `host`: Ollama server URL
- `default_model`: Default model for queries
- `default_system_prompt`: Default system prompt for all queries
- `max_history_length`: Maximum messages in history
- `max_history_tokens`: Maximum tokens in history (approximate)

#### query()

```python
async def query(
    model: str | None = None,
    messages: list[Message] | list[dict] | None = None,
    prompt: str | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    top_k: int | None = None,
    num_predict: int | None = None,
    stop: list[str] | None = None,
    repeat_penalty: float | None = None,
    seed: int | None = None,
    format: Literal["text", "json"] | None = None,
    stream: bool = False,
    keep_alive: str | int = "5m",
    session_id: str | None = None,
    timeout_ms: int = 120000,
    max_retries: int = 3,
    retry_backoff: float = 1.0,
    metadata: dict[str, Any] | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    extra_context: str | None = None,
    documents: list[str] | None = None,
) -> OllamaQueryResult | AsyncIterator[str]
```

**Core Parameters:**
- `model`: Model name (uses default if not provided)
- `messages`: Full chat history or None to use session history
- `prompt`: Shortcut for single user message
- `system_prompt`: System prompt (overrides default)

**Generation Parameters:**
- `temperature`: Sampling temperature (default: 0.7)
- `top_p`: Nucleus sampling (default: 0.9)
- `top_k`: Top-k sampling (default: 40)
- `num_predict`: Maximum tokens to generate
- `stop`: Stop sequences
- `repeat_penalty`: Repetition penalty (default: 1.1)
- `seed`: Random seed for reproducibility

**Output Control:**
- `format`: Output format ("text" or "json")
- `stream`: Enable streaming mode

**Session & Retry:**
- `session_id`: Session ID for conversation tracking
- `keep_alive`: Model keep-alive duration (e.g., "5m", 0, -1)
- `timeout_ms`: Request timeout in milliseconds
- `max_retries`: Maximum retry attempts
- `retry_backoff`: Exponential backoff multiplier

**Metadata & Extensions:**
- `metadata`: Additional metadata for logging
- `tools`: Tool definitions (future use)
- `tool_choice`: Tool selection strategy (future use)
- `extra_context`: Additional context (for RAG)
- `documents`: Document list (for RAG)

**Returns:**
- `OllamaQueryResult` for non-streaming queries
- `AsyncIterator[str]` for streaming queries

### Session Management

```python
# Get existing session
session = manager.get_session("user_123")

# Create new session
session = manager.create_session("user_456")

# Delete session
manager.delete_session("user_123")

# Clear all sessions
manager.clear_all_sessions()
```

### Utility Methods

```python
# Get usage statistics
stats = manager.get_statistics()
# {
#     "total_requests": 150,
#     "total_tokens_generated": 45000,
#     "total_errors": 2,
#     "model_usage": {"llama2": 100, "codellama": 50},
#     "active_sessions": 5
# }

# List available models
models = await manager.list_models()

# Pull a model
success = await manager.pull_model("llama2:13b")
```

## Usage Examples

### Example 1: Code Generation with JSON Output

```python
result = await manager.query(
    model="codellama",
    prompt="Generate a Python function to calculate fibonacci numbers. Return as JSON with 'code' and 'explanation' fields.",
    format="json",
    temperature=0.3,  # Lower temperature for more focused output
    num_predict=1000
)

import json
response = json.loads(result.content)
print(response["code"])
print(response["explanation"])
```

### Example 2: RAG-Style Query with Context

```python
# Provide context documents
documents = [
    "The company was founded in 2020 by Jane Smith.",
    "Our main product is an AI-powered chatbot.",
    "We have 50 employees across 3 offices."
]

result = await manager.query(
    model="llama2",
    prompt="When was the company founded and by whom?",
    documents=documents,
    temperature=0.2  # Lower temperature for factual queries
)
```

### Example 3: Multi-Turn Customer Support

```python
# Customer support session
session_id = f"support_{user_id}"

# First message
await manager.query(
    prompt="My order hasn't arrived yet",
    session_id=session_id,
    system_prompt="You are a helpful customer support agent"
)

# Follow-up (remembers context)
await manager.query(
    prompt="The order number is #12345",
    session_id=session_id
)

# Get conversation history
session = manager.get_session(session_id)
messages = session.get_messages()
```

### Example 4: Retry Logic for Reliability

```python
# Configure aggressive retry for critical requests
result = await manager.query(
    prompt="Analyze this medical report...",
    max_retries=5,
    retry_backoff=2.0,  # 2s, 4s, 8s, 16s, 32s
    timeout_ms=180000   # 3 minute timeout
)
```

### Example 5: Streaming with Progress Indicator

```python
print("Generating response... ", end="")
full_response = ""

async for chunk in await manager.query(
    prompt="Explain quantum computing in detail",
    stream=True
):
    print(chunk, end="", flush=True)
    full_response += chunk

print("\n\nComplete!")
```

## ConversationHistory

The `ConversationHistory` class manages message history for sessions:

```python
from source.services.ollama_request_manager import ConversationHistory

# Create history
history = ConversationHistory(
    session_id="user_123",
    max_length=50,      # Keep last 50 messages
    max_tokens=4000,    # Approximate token limit
    system_prompt="You are a helpful assistant"
)

# Add messages
history.add_user_message("Hello!")
history.add_assistant_message("Hi there!")

# Get messages
messages = history.get_messages()

# Get statistics
stats = history.get_statistics()

# Export/import
data = history.to_dict()
history2 = ConversationHistory.from_dict(data)
```

## Data Models

### OllamaQueryResult

```python
@dataclass
class OllamaQueryResult:
    content: str                    # Generated text
    model: str                      # Model used
    done: bool                      # Request complete
    total_duration: int | None      # Total time (ns)
    load_duration: int | None       # Model load time (ns)
    prompt_eval_count: int | None   # Input tokens
    prompt_eval_duration: int | None # Input processing time (ns)
    eval_count: int | None          # Output tokens
    eval_duration: int | None       # Output generation time (ns)
    metadata: dict                  # Custom metadata
```

### GenerationConfig

```python
@dataclass
class GenerationConfig:
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    num_predict: int | None = None
    stop: list[str] = []
    repeat_penalty: float = 1.1
    seed: int | None = None
```

## Best Practices

1. **Use Sessions for Conversations**: Always use `session_id` for multi-turn interactions
2. **Set Appropriate Limits**: Configure `max_history_length` and `max_history_tokens` based on model context window
3. **Lower Temperature for Facts**: Use temperature 0.1-0.3 for factual/analytical tasks
4. **Higher Temperature for Creativity**: Use temperature 0.7-0.9 for creative tasks
5. **Use JSON Mode**: When you need structured output, use `format="json"`
6. **Monitor Statistics**: Regularly check `get_statistics()` for usage patterns
7. **Clean Up Sessions**: Delete inactive sessions to free memory
8. **Set Timeouts**: Use appropriate `timeout_ms` based on expected response time
9. **Handle Streaming**: Always consume streaming responses fully

## Integration with Services

Add to your `ServicesManager`:

```python
from source.services.ollama_request_manager import OllamaRequestManager

class ServicesManager:
    def __init__(self, context, ...):
        # ... other services
        self.ollama_manager = OllamaRequestManager(
            context=context,
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            default_model=os.getenv("OLLAMA_MODEL", "llama2")
        )
```

Then use in your cogs:

```python
async def summarize_transcript(self, ctx, transcript_text):
    result = await self.bot.services.ollama_manager.query(
        model="llama2",
        prompt=f"Summarize this meeting transcript:\n\n{transcript_text}",
        temperature=0.3,
        num_predict=500
    )
    await ctx.send(result.content)
```

## Future Enhancements

The manager is designed to be extended with:

- **Function Calling**: `tools` and `tool_choice` parameters
- **RAG Integration**: `documents` and `extra_context` for retrieval-augmented generation
- **Embeddings**: Future support for Ollama's embedding endpoint
- **Batch Processing**: Parallel query execution
- **Caching**: Response caching for identical queries
- **Logging Integration**: Enhanced logging with trace IDs

## License

Same as parent project.
