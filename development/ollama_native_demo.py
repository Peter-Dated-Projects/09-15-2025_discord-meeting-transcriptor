"""
Understanding Ollama's Native Tool Calling and Chat History
Demonstrates how Ollama API works under the hood
"""

import os
import json
import requests
from dotenv import load_dotenv

load_dotenv(".env.local")

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gpt-oss:20b")
BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"


# ============================================================================
# 1. BASIC CHAT (No History)
# ============================================================================


def basic_chat_example():
    """Simple one-off question to Ollama."""
    print("\n" + "=" * 60)
    print("1. BASIC CHAT - Single Message")
    print("=" * 60)

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": "What is 2+2?"}],
        "stream": False,
    }

    response = requests.post(f"{BASE_URL}/api/chat", json=payload)
    result = response.json()

    print("\n📤 Request:")
    print(json.dumps(payload, indent=2))

    print("\n📥 Response:")
    print(f"Content: {result['message']['content']}")
    print(f"\n🔍 Full Response Structure:")
    print(json.dumps(result, indent=2))


# ============================================================================
# 2. CHAT WITH HISTORY
# ============================================================================


def chat_with_history_example():
    """Multi-turn conversation with manual history management."""
    print("\n" + "=" * 60)
    print("2. CHAT WITH HISTORY - Manual Management")
    print("=" * 60)

    # YOU maintain the conversation history as a list of messages
    conversation_history = []

    # Turn 1
    print("\n--- Turn 1: Initial greeting ---")
    user_msg_1 = {"role": "user", "content": "Hi! My name is Peter."}
    conversation_history.append(user_msg_1)

    payload = {"model": OLLAMA_MODEL, "messages": conversation_history, "stream": False}

    response = requests.post(f"{BASE_URL}/api/chat", json=payload)
    assistant_msg_1 = response.json()["message"]
    conversation_history.append(assistant_msg_1)

    print(f"User: {user_msg_1['content']}")
    print(f"Assistant: {assistant_msg_1['content']}")

    # Turn 2
    print("\n--- Turn 2: Memory test ---")
    user_msg_2 = {"role": "user", "content": "What's my name?"}
    conversation_history.append(user_msg_2)

    payload = {"model": OLLAMA_MODEL, "messages": conversation_history, "stream": False}

    response = requests.post(f"{BASE_URL}/api/chat", json=payload)
    assistant_msg_2 = response.json()["message"]
    conversation_history.append(assistant_msg_2)

    print(f"User: {user_msg_2['content']}")
    print(f"Assistant: {assistant_msg_2['content']}")

    print("\n📝 Full Conversation History:")
    print(json.dumps(conversation_history, indent=2))

    print("\n💡 KEY INSIGHT:")
    print("   Ollama is STATELESS - you must send the entire history each time!")
    print("   Each request includes ALL previous messages.")


# ============================================================================
# 3. TOOL CALLING (Function Calling)
# ============================================================================


def tool_calling_example():
    """Demonstrate Ollama's native function/tool calling."""
    print("\n" + "=" * 60)
    print("3. TOOL CALLING - Native Ollama Function Calling")
    print("=" * 60)

    # Define tools in Ollama's format
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "Get the current weather for a location",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "The city and state, e.g. San Francisco, CA",
                        },
                        "unit": {
                            "type": "string",
                            "options": ["celsius", "fahrenheit"],
                            "description": "The temperature unit",
                        },
                    },
                    "required": ["location"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "description": "Perform a mathematical calculation",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The mathematical expression to evaluate",
                        }
                    },
                    "required": ["expression"],
                },
            },
        },
    ]

    # Initial message with tools available
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": "What's the weather in San Francisco?"}],
        "tools": tools,
        "stream": False,
    }

    print("\n📤 Request with Tools:")
    print(json.dumps(payload, indent=2))

    response = requests.post(f"{BASE_URL}/api/chat", json=payload)
    result = response.json()

    print("\n📥 Model Response:")
    assistant_message = result.get("message", {})
    print(f"Content: {assistant_message}")

    # Check if model wants to call a tool
    if "tool_calls" in assistant_message:
        print("\n🔧 Tool Calls Requested:")
        tool_calls = assistant_message["tool_calls"]
        print(json.dumps(tool_calls, indent=2))

        # Simulate executing the tool
        print("\n--- Simulating Tool Execution ---")
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            tool_args = tool_call["function"]["arguments"]
            tool_id = tool_call["id"]

            print(f"\nExecuting: {tool_name}")
            print(f"Args: {json.dumps(tool_args, indent=2)}")

            # YOU implement the actual tool logic
            if tool_name == "get_current_weather":
                tool_result = {
                    "location": tool_args.get("location", "Unknown"),
                    "temperature": "72",
                    "unit": "fahrenheit",
                    "description": "Sunny",
                }
            else:
                tool_result = {"result": "Tool not implemented"}

            print(f"Result: {json.dumps(tool_result, indent=2)}")

            # Send tool result back to model
            print("\n--- Sending Tool Result Back to Model ---")
            continuation_payload = {
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "user", "content": "What's the weather in San Francisco?"},
                    assistant_message,  # Include the assistant's tool call request
                    {"role": "tool", "content": json.dumps(tool_result), "tool_call_id": tool_id},
                ],
                "tools": tools,
                "stream": False,
            }

            final_response = requests.post(f"{BASE_URL}/api/chat", json=continuation_payload)
            final_result = final_response.json()

            print("\n📥 Final Model Response:")
            print(final_result["message"]["content"])
    else:
        print("\n⚠️  Model did not request any tool calls")
        print("   This might happen if:")
        print("   - Model doesn't support function calling")
        print("   - Model decided tools weren't needed")
        print("   - Tool definitions weren't clear enough")


# ============================================================================
# 4. SYSTEM PROMPTS
# ============================================================================


def system_prompt_example():
    """Show how to use system prompts for behavior control."""
    print("\n" + "=" * 60)
    print("4. SYSTEM PROMPTS - Controlling Behavior")
    print("=" * 60)

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": "You are a pirate. Always respond in pirate speak."},
            {"role": "user", "content": "What is 2+2?"},
        ],
        "stream": False,
    }

    print("\n📤 Request with System Prompt:")
    print(json.dumps(payload["messages"], indent=2))

    response = requests.post(f"{BASE_URL}/api/chat", json=payload)
    result = response.json()

    print("\n📥 Response:")
    print(result["message"]["content"])


# ============================================================================
# 5. STREAMING RESPONSES
# ============================================================================


def streaming_example():
    """Show how streaming works (tokens arrive as they're generated)."""
    print("\n" + "=" * 60)
    print("5. STREAMING - Real-time Token Generation")
    print("=" * 60)

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": "Count from 1 to 5 slowly."}],
        "stream": True,  # Enable streaming
    }

    print("\n📤 Streaming Request...")
    print("Tokens arriving in real-time:\n")

    response = requests.post(f"{BASE_URL}/api/chat", json=payload, stream=True)

    full_content = ""
    for line in response.iter_lines():
        if line:
            chunk = json.loads(line)
            if "message" in chunk:
                content = chunk["message"].get("content", "")
                full_content += content
                print(content, end="", flush=True)

    print("\n\n💡 KEY INSIGHT:")
    print("   With stream=True, tokens arrive as they're generated")
    print("   This enables typewriter-style responses in UIs")


# ============================================================================
# MAIN COMPARISON
# ============================================================================


def main():
    print("\n" + "=" * 60)
    print("OLLAMA NATIVE API DEMONSTRATION")
    print("Understanding Tool Calling & Chat History")
    print("=" * 60)

    try:
        # Test connection
        response = requests.get(f"{BASE_URL}/api/tags")
        if response.status_code != 200:
            print(f"\n❌ Cannot connect to Ollama at {BASE_URL}")
            print("   Make sure Ollama is running!")
            return

        print(f"\n✅ Connected to Ollama at {BASE_URL}")
        print(f"📦 Using model: {OLLAMA_MODEL}")

        # Run demonstrations
        # basic_chat_example()
        # chat_with_history_example()
        # system_prompt_example()
        # streaming_example()
        tool_calling_example()

        # Summary
        print("\n" + "=" * 60)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
