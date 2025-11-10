"""
Redesigned Chatbot System with Reasoning Display and Tool Support
Uses Ollama + LangChain + OpenAI Harmony for proper reasoning parsing
"""

import os
import re
import json
import shutil
import datetime as dt
import textwrap
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.tools import tool
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

try:
    from openai_harmony import parse_harmony_response

    HARMONY_AVAILABLE = True
except ImportError:
    HARMONY_AVAILABLE = False
    # Warning will be shown in main() only when running as script


# ============================================================================
# Configuration
# ============================================================================

load_dotenv(".env.local")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"


# ============================================================================
# Example Tools
# ============================================================================


@tool
def get_current_time() -> str:
    """Get the current time in HH:MM:SS format."""
    return dt.datetime.now().strftime("%H:%M:%S")


@tool
def calculate(expression: str) -> str:
    """
    Safely evaluate a mathematical expression.

    Args:
        expression: A string containing a mathematical expression (e.g., "2 + 2", "15 * 7")
    """
    try:
        # Safe eval with limited namespace
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except Exception as e:
        return f"Error calculating '{expression}': {str(e)}"


@tool
def search_memory(query: str) -> str:
    """
    Search through conversation history for specific information.

    Args:
        query: What to search for in the conversation history
    """
    # This is a placeholder - you could implement actual semantic search
    return f"Searching memory for: {query}"


# List of available tools
AVAILABLE_TOOLS = [get_current_time, calculate, search_memory]


# ============================================================================
# System Prompt with OpenAI Harmony Format
# ============================================================================

SYSTEM_PROMPT = """You are a thoughtful and precise assistant with exceptional memory and research capabilities.

# Response Format

Use this exact structure for all responses:

<think>
[Your internal reasoning process. Think step-by-step about:
- What information you have from the conversation history
- What the user is asking for
- Whether you need to use any tools (and which ones)
- How to best answer the question]
</think>

<answer>
[Your final response to the user. Be clear, concise, and helpful.]
</answer>

# Available Tools

You have access to these tools:
- get_current_time(): Get the current time
- calculate(expression): Evaluate math expressions
- search_memory(query): Search conversation history

# Important Notes
- Always include both <think> and <answer> sections
- Your thinking shows your reasoning process
- Use tools when they would be helpful
- Be accurate and verify information when unsure"""


# ============================================================================
# Message Parsing
# ============================================================================


@dataclass
class ParsedMessage:
    """Structured representation of a parsed message."""

    thinking: str = ""
    answer: str = ""
    raw_content: str = ""
    tool_calls: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.tool_calls is None:
            self.tool_calls = []


def parse_message(content: str, message: Optional[BaseMessage] = None) -> ParsedMessage:
    """
    Parse a message to extract thinking, answer, and tool calls.
    Uses openai-harmony if available, falls back to regex parsing.
    Also checks for native Ollama reasoning tokens.

    Args:
        content: The message content string
        message: Optional full message object for accessing metadata

    Returns:
        ParsedMessage with extracted components
    """
    parsed = ParsedMessage(raw_content=content)

    # Check for native reasoning in response_metadata (Ollama API)
    if message and hasattr(message, "response_metadata"):
        metadata = message.response_metadata

        # Some models (like deepseek-r1) expose reasoning separately
        if "reasoning_content" in metadata:
            parsed.thinking = metadata["reasoning_content"]

        # Check for thinking in the message field
        if "message" in metadata and isinstance(metadata["message"], dict):
            msg_dict = metadata["message"]
            if "reasoning" in msg_dict:
                parsed.thinking = msg_dict["reasoning"]
            if "thinking" in msg_dict:
                parsed.thinking = msg_dict["thinking"]

    # Try using openai-harmony for proper Harmony format parsing
    if HARMONY_AVAILABLE and not parsed.thinking:
        try:
            harmony_parsed = parse_harmony_response(content)

            # openai-harmony returns a dict with 'thinking' and 'response' keys
            if isinstance(harmony_parsed, dict):
                if "thinking" in harmony_parsed and harmony_parsed["thinking"]:
                    parsed.thinking = harmony_parsed["thinking"]
                if "response" in harmony_parsed and harmony_parsed["response"]:
                    parsed.answer = harmony_parsed["response"]
            elif hasattr(harmony_parsed, "thinking") and hasattr(harmony_parsed, "response"):
                # In case it returns an object
                if harmony_parsed.thinking:
                    parsed.thinking = harmony_parsed.thinking
                if harmony_parsed.response:
                    parsed.answer = harmony_parsed.response
        except Exception as e:
            # If harmony parsing fails, fall back to regex
            pass

    # Fallback: Extract <think> or <thinking> tags from content using regex
    if not parsed.thinking:
        think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
        if think_match:
            parsed.thinking = think_match.group(1).strip()
        else:
            # Also try <thinking> for compatibility
            thinking_match = re.search(r"<thinking>(.*?)</thinking>", content, re.DOTALL)
            if thinking_match:
                parsed.thinking = thinking_match.group(1).strip()

    # Extract <answer> section from content if not already set
    if not parsed.answer:
        answer_match = re.search(r"<answer>(.*?)</answer>", content, re.DOTALL)
        if answer_match:
            parsed.answer = answer_match.group(1).strip()
        else:
            # If no answer tags, use content minus thinking tags as answer
            clean_content = content
            if parsed.thinking:
                clean_content = re.sub(r"<think>.*?</think>", "", clean_content, flags=re.DOTALL)
                clean_content = re.sub(
                    r"<thinking>.*?</thinking>", "", clean_content, flags=re.DOTALL
                )
            clean_content = clean_content.strip()
            if clean_content:
                parsed.answer = clean_content

    # Check for actual LangChain tool calls in message metadata
    if message and hasattr(message, "tool_calls") and message.tool_calls:
        parsed.tool_calls = message.tool_calls
    elif message and hasattr(message, "additional_kwargs"):
        if "tool_calls" in message.additional_kwargs:
            parsed.tool_calls = message.additional_kwargs["tool_calls"]

    return parsed


# ============================================================================
# Display Formatting
# ============================================================================


class MessageFormatter:
    """Handles formatting messages for display."""

    def __init__(self, width: Optional[int] = None):
        if width is None:
            term_w = shutil.get_terminal_size((100, 20)).columns
            self.width = max(60, min(120, term_w - 4))
        else:
            self.width = width

        self.role_tags = {
            "human": "USER",
            "ai": "ASSISTANT",
            "system": "SYSTEM",
            "tool": "TOOL",
        }

    def _timestamp(self) -> str:
        """Get current timestamp."""
        return dt.datetime.now().strftime("%H:%M:%S")

    def _border(self) -> str:
        """Get border line."""
        return "─" * min(self.width, 80)

    def _wrap(self, text: str) -> str:
        """Wrap text to width."""
        return textwrap.fill(text.strip(), width=self.width)

    def format_message(self, message: BaseMessage) -> str:
        """
        Format a single message for display.

        Args:
            message: The message to format

        Returns:
            Formatted string ready for printing
        """
        role = self.role_tags.get(message.type, message.type.upper())
        parsed = parse_message(message.content, message)

        result = []
        border = self._border()

        # Display thinking section
        if parsed.thinking:
            result.append(f"[{self._timestamp()}] {role} (THINKING)")
            result.append(self._wrap(parsed.thinking))
            result.append(border)

        # Display tool calls
        if parsed.tool_calls:
            result.append(f"[{self._timestamp()}] {role} (TOOL CALLS)")
            for tool_call in parsed.tool_calls:
                if isinstance(tool_call, dict):
                    tool_name = tool_call.get("name", "unknown")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", "N/A")

                    tool_info = (
                        f"Tool: {tool_name}\nArgs: {json.dumps(tool_args, indent=2)}\nID: {tool_id}"
                    )
                    result.append(self._wrap(tool_info))
            result.append(border)

        # Display answer section
        if parsed.answer:
            result.append(f"[{self._timestamp()}] {role}")
            result.append(self._wrap(parsed.answer))
            result.append(border)

        # Fallback: display raw content if no structured sections found
        if not parsed.thinking and not parsed.answer and not parsed.tool_calls:
            result.append(f"[{self._timestamp()}] {role}")
            result.append(self._wrap(message.content))
            result.append(border)

        return "\n".join(result)

    def format_history(self, messages: List[BaseMessage], session_id: str = "") -> str:
        """
        Format entire conversation history.

        Args:
            messages: List of messages to format
            session_id: Optional session identifier

        Returns:
            Formatted conversation string
        """
        header = "=" * 12 + f" Conversation: {session_id} " + "=" * 12
        footer = "=" * (26 + len(session_id))

        formatted_messages = [self.format_message(msg) for msg in messages]

        return "\n" + header + "\n" + "\n".join(formatted_messages) + "\n" + footer


# ============================================================================
# Chatbot Core
# ============================================================================


class Chatbot:
    """
    Main chatbot class with memory and tool support.
    """

    def __init__(
        self,
        model: str = OLLAMA_MODEL,
        base_url: str = BASE_URL,
        temperature: float = 0.7,
        tools: Optional[List] = None,
    ):
        """
        Initialize the chatbot.

        Args:
            model: Ollama model name
            base_url: Ollama server URL
            temperature: Model temperature (0.0 to 1.0)
            tools: List of LangChain tools to make available
        """
        print(f"Initializing chatbot with model: {model} at {base_url}")

        # Initialize LLM
        self.llm = ChatOllama(
            model=model,
            base_url=base_url,
            temperature=temperature,
        )

        # Bind tools if provided
        if tools:
            self.llm = self.llm.bind_tools(tools)
            self.tools = tools
        else:
            self.tools = []

        # Create prompt template
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                MessagesPlaceholder(variable_name="history"),
                ("human", "{input}"),
            ]
        )

        # Create chain with memory
        self._store: Dict[str, InMemoryChatMessageHistory] = {}
        self.chain = RunnableWithMessageHistory(
            self.prompt | self.llm,
            get_session_history=self._get_history,
            input_messages_key="input",
            history_messages_key="history",
        )

        # Initialize formatter
        self.formatter = MessageFormatter()

    def _get_history(self, session_id: str) -> InMemoryChatMessageHistory:
        """Get or create history for a session."""
        return self._store.setdefault(session_id, InMemoryChatMessageHistory())

    def ask(self, session_id: str, text: str, verbose: bool = False) -> str:
        """
        Ask the chatbot a question.

        Args:
            session_id: Session identifier for conversation tracking
            text: User's question/input
            verbose: If True, print the formatted response

        Returns:
            The assistant's response content
        """
        response = self.chain.invoke(
            {"input": text},
            config={"configurable": {"session_id": session_id}},
        )

        if verbose:
            print(self.formatter.format_message(response))

        return response.content

    def reset(self, session_id: str):
        """Clear history for a session."""
        self._store.pop(session_id, None)
        print(f"Session '{session_id}' reset.")

    def print_history(self, session_id: str):
        """Print formatted conversation history."""
        history = self._get_history(session_id)
        print(self.formatter.format_history(history.messages, session_id))

    def get_sessions(self) -> List[str]:
        """Get list of active session IDs."""
        return list(self._store.keys())

    def debug_message(self, session_id: str, text: str):
        """
        Send a message and print detailed debug information about the response.
        Useful for understanding what Ollama returns natively.

        Args:
            session_id: Session identifier
            text: User input
        """
        print("\n" + "=" * 60)
        print("DEBUG MODE - Raw Response Analysis")
        print("=" * 60 + "\n")

        response = self.chain.invoke(
            {"input": text},
            config={"configurable": {"session_id": session_id}},
        )

        print("📋 Message Type:", type(response).__name__)
        print("\n📝 Content (first 500 chars):")
        print(response.content[:500])
        print("...\n" if len(response.content) > 500 else "\n")

        if hasattr(response, "response_metadata"):
            print("🔍 Response Metadata:")
            for key, value in response.response_metadata.items():
                if key in ["message", "reasoning_content", "thinking"]:
                    print(f"  {key}: {value}")
                elif isinstance(value, (str, int, float, bool)):
                    print(f"  {key}: {value}")
            print()

        if hasattr(response, "tool_calls") and response.tool_calls:
            print("🔧 Tool Calls:")
            for tc in response.tool_calls:
                print(f"  {tc}")
            print()

        if hasattr(response, "additional_kwargs") and response.additional_kwargs:
            print("➕ Additional Kwargs:")
            for key, value in response.additional_kwargs.items():
                print(f"  {key}: {value}")
            print()

        print("=" * 60)
        print("Formatted Output:")
        print("=" * 60)
        print(self.formatter.format_message(response))

        return response


# ============================================================================
# Main / Demo
# ============================================================================


def main():
    """Demo the chatbot system."""

    # Create chatbot with tools
    bot = Chatbot(tools=AVAILABLE_TOOLS)

    print("\n" + "=" * 60)
    print("Chatbot System Demo")
    if HARMONY_AVAILABLE:
        print("✅ Using openai-harmony for parsing")
    else:
        print("⚠️  Using regex fallback (install openai-harmony for better parsing)")
    print("=" * 60 + "\n")

    # First, test if native reasoning is supported
    print("🔬 Testing Native Reasoning Support...")
    print("-" * 60)
    bot.debug_message("test", "What is 2+2? Think step by step.")
    print("\n")

    # Example conversation
    session = "demo"

    print("Question 1: Who are you?")
    bot.ask(session, "Hello, who are you?", verbose=True)
    print("\n")

    print("Question 2: What time is it?")
    bot.ask(session, "What time is it right now?", verbose=True)
    print("\n")

    print("Question 3: Calculate something")
    bot.ask(session, "What is 25 * 17?", verbose=True)
    print("\n")

    print("Question 4: Memory test")
    bot.ask(session, "My name is Peter. Remember that.", verbose=True)
    print("\n")

    print("Question 5: Recall from memory")
    bot.ask(session, "What's my name?", verbose=True)
    print("\n")

    # Show full history
    print("\n" + "=" * 60)
    print("Full Conversation History")
    print("=" * 60)
    bot.print_history(session)


if __name__ == "__main__":
    main()
