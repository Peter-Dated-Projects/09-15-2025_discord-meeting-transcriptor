# Chatbot System v2

A sophisticated chatbot system using **Ollama**, **LangChain**, and **OpenAI Harmony** format for transparent reasoning display and tool usage.

## Features

- 🧠 **Reasoning Display**: Shows the model's thinking process using OpenAI Harmony format
- 🛠️ **Tool Support**: Integrates LangChain tools with clear execution visibility
- 💾 **Session Memory**: Multi-session conversation history management
- 🎨 **Beautiful Formatting**: Clean, readable output with timestamps and sections
- 🔍 **Debug Mode**: Inspect raw Ollama responses to understand native reasoning support

## Architecture

### Three-Layer Parsing Strategy

1. **Native Ollama Reasoning**: Checks `response_metadata` for native reasoning tokens (e.g., deepseek-r1)
2. **OpenAI Harmony Parser**: Uses `openai-harmony` library for proper `<think>` and `<answer>` parsing
3. **Regex Fallback**: Manual XML tag extraction if harmony is unavailable

### Components

- **`ParsedMessage`**: Structured message representation
- **`MessageFormatter`**: Handles all display logic with customizable width
- **`Chatbot`**: Main interface with memory and tool management

## Installation

```bash
# Install dependencies
pip install -r requirements-chatbot.txt

# Or manually:
pip install langchain-ollama langchain-core python-dotenv openai-harmony
```

## Configuration

Create a `.env.local` file:

```env
OLLAMA_MODEL=gpt-oss:20b
OLLAMA_HOST=localhost
OLLAMA_PORT=11434
```

## Usage

### Basic Usage

```python
from chatbot_v2 import Chatbot, AVAILABLE_TOOLS

# Create chatbot with tools
bot = Chatbot(tools=AVAILABLE_TOOLS)

# Ask a question (with verbose output)
response = bot.ask("session1", "What is 15 * 7?", verbose=True)

# Print conversation history
bot.print_history("session1")

# Reset session
bot.reset("session1")
```

### Debug Mode

```python
# Inspect raw Ollama response
bot.debug_message("test", "What is 2+2?")
```

This shows:
- Message type and content
- Response metadata (native reasoning if supported)
- Tool calls
- Additional kwargs
- Formatted output

### Custom Tools

```python
from langchain_core.tools import tool

@tool
def my_custom_tool(param: str) -> str:
    """Description of what the tool does."""
    return f"Result for {param}"

# Use custom tools
bot = Chatbot(tools=[my_custom_tool])
```

## Running the Demo

```bash
python chatbot_v2.py
```

The demo will:
1. Test native reasoning support with debug output
2. Run example conversations
3. Demonstrate tool usage
4. Show memory recall
5. Display full conversation history

## OpenAI Harmony Format

The system uses OpenAI's Harmony format for structured responses:

```xml
<think>
[Model's internal reasoning process]
</think>

<answer>
[Final response to the user]
</answer>
```

### Benefits:
- **Transparency**: See exactly how the model arrives at answers
- **Debugging**: Understand model behavior and errors
- **Trust**: Verify reasoning before accepting conclusions
- **Learning**: Study the model's problem-solving approach

## Tool Integration

The system includes three example tools:

1. **`get_current_time()`**: Returns current time
2. **`calculate(expression)`**: Safely evaluates math expressions
3. **`search_memory(query)`**: Searches conversation history

Tool calls are displayed with:
- Tool name
- Arguments (formatted JSON)
- Call ID

## Output Format

```
[HH:MM:SS] ASSISTANT (THINKING)
The user is asking about... I need to consider...
────────────────────────────────────────────────────────────────

[HH:MM:SS] ASSISTANT (TOOL CALLS)
Tool: calculate
Args: {"expression": "15 * 7"}
ID: call_abc123
────────────────────────────────────────────────────────────────

[HH:MM:SS] ASSISTANT
The answer is 105.
────────────────────────────────────────────────────────────────
```

## Advanced Usage

### Custom Width

```python
from chatbot_v2 import MessageFormatter

formatter = MessageFormatter(width=100)
```

### Multiple Sessions

```python
# Different conversations
bot.ask("user1", "Hello!")
bot.ask("user2", "Hi there!")

# List all sessions
sessions = bot.get_sessions()
print(sessions)  # ['user1', 'user2']
```

### Programmatic Access

```python
# Get parsed response without printing
response = bot.ask("session", "Question?", verbose=False)

# Access message history directly
history = bot._get_history("session")
messages = history.messages
```

## Troubleshooting

### "openai-harmony not installed"
```bash
pip install openai-harmony
```

### Model doesn't show thinking
- Check if model supports reasoning (try `deepseek-r1`)
- Verify system prompt includes Harmony format instructions
- Use debug mode to inspect raw responses

### Tool calls not appearing
- Ensure tools are passed to `Chatbot(tools=...)`
- Check if model supports function calling
- Verify tool descriptions are clear

## Contributing

To add new features:

1. **New Tools**: Add `@tool` decorated functions
2. **Custom Formatters**: Subclass `MessageFormatter`
3. **Alternative Parsers**: Modify `parse_message()` function

## License

See main project LICENSE file.
