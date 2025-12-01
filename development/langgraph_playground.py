"""
Playground for testing LangGraph subroutines with a real Ollama LLM call.
"""

import asyncio
from typing import Any, Dict, List, Literal
import json
import uuid  # Add this import

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# --- Import MCP Components ---
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from source.services.chat.mcp.common.tool import BaseTool
from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.gpu.ollama_request_manager.manager import OllamaRequestManager


# --- Mock Application Context for Ollama Manager ---
class MockLoggingService:
    async def info(self, msg: str):
        print(f"[INFO] {msg}")

    async def error(self, msg: str):
        print(f"[ERROR] {msg}")

    async def debug(self, msg: str):
        print(f"[DEBUG] {msg}")

    async def warning(self, msg: str):
        print(f"[WARN] {msg}")


class MockServices:
    def __init__(self):
        self.logging_service = MockLoggingService()


class MockContext:
    def __init__(self):
        self.services = MockServices()
        self.server_manager = None


# --- Global instances for the playground ---
mock_context = MockContext()
ollama_manager = OllamaRequestManager(context=mock_context)

# --- 1. Define a simple tool and a callback function ---


def add(a: float, b: float) -> float:
    """Adds two numbers.
    Args:
        a (float): The first number.
        b (float): The second number.
    """
    print(f"\n--- Tool: 'add' called with a={a}, b={b} ---")
    return a + b


add_tool = BaseTool(
    func=add,
    name="add",
    description="Adds two numbers together.",
    arguments={"a": 10.23, "b": 5.424},  # Example arguments to guide the LLM
)
# The executor needs a map of tool names to tool objects
tool_executor_map = {"add": add_tool}


def step_callback(step_info: dict):
    """A simple callback to print the details of each step."""
    print(f"\n[Step {step_info['step_count']}] {step_info['step_name']}")
    last_message = step_info["current_state"]["messages"][-1]

    # Show message type and content concisely
    msg_type = type(last_message).__name__
    if hasattr(last_message, "content") and last_message.content:
        content = last_message.content
        print(
            f"  → {msg_type}: {content[:100]}..."
            if len(content) > 100
            else f"  → {msg_type}: {content}"
        )
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        print(f"  → Tool calls: {len(last_message.tool_calls)} call(s)")


# --- 2. Define the Agentic Workflow (as a Subroutine) ---


def convert_lc_messages_to_ollama(messages: List[BaseMessage]) -> List[Dict]:
    """Converts LangChain messages to the dict format OllamaRequestManager expects."""
    ollama_msgs = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            ollama_msgs.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            # Include assistant message with tool calls if present
            msg_dict = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                # Convert LangChain tool calls back to Ollama format
                msg_dict["tool_calls"] = [
                    {"id": tc["id"], "function": {"name": tc["name"], "arguments": tc["args"]}}
                    for tc in msg.tool_calls
                ]
            ollama_msgs.append(msg_dict)
        elif isinstance(msg, ToolMessage):
            # Add tool results as tool messages
            ollama_msgs.append(
                {"role": "tool", "content": msg.content, "tool_call_id": msg.tool_call_id}
            )
    return ollama_msgs


# This node now makes a real LLM call
async def agent_node(state: SubroutineState) -> Dict[str, List[BaseMessage]]:
    """
    Calls the Ollama model with the current state and a tool, then returns
    the model's response as an AIMessage.
    """
    print("\n🤖 Agent: Calling LLM...")

    # Get the schema of the 'add' tool for the LLM
    add_tool_schema = add_tool.to_mcp_schema()

    # Convert LangChain message history to the format Ollama manager needs
    ollama_messages = convert_lc_messages_to_ollama(state["messages"])
    print(f"   Conversation history: {len(ollama_messages)} message(s)")

    # Define a system prompt to encourage tool use
    system_prompt = (
        "You are a helpful assistant. You must use the provided tools to answer "
        "questions whenever possible."
    )

    # Call the Ollama manager
    response = await ollama_manager.query(
        model="gpt-oss:20b",
        messages=ollama_messages,
        system_prompt=system_prompt,
        tools=[add_tool_schema],
        stream=False,
    )

    # Display thinking if available
    if response.thinking:
        print(f"\n💭 Model thinking: {response.thinking}")

    # Convert Ollama tool calls to the format LangChain's AIMessage expects
    langchain_tool_calls = []
    if response.tool_calls:
        for ollama_tc in response.tool_calls:
            # Handle both dict and object formats
            if isinstance(ollama_tc, dict):
                tool_name = ollama_tc["function"]["name"]
                tool_args = ollama_tc["function"]["arguments"]
                tool_id = ollama_tc.get("id", str(uuid.uuid4()))
            else:
                # It's an object, access via attributes
                tool_name = ollama_tc.function.name
                tool_args = ollama_tc.function.arguments
                tool_id = getattr(ollama_tc, "id", str(uuid.uuid4()))

            print(
                f"   🔧 Tool call: {tool_name}({', '.join(f'{k}={v}' for k, v in tool_args.items())})"
            )

            langchain_tool_calls.append(
                {
                    "name": tool_name,
                    "args": tool_args,
                    "id": tool_id,
                }
            )

    # Wrap the response in an AIMessage for the graph state
    ai_response = AIMessage(
        content=response.content,
        tool_calls=langchain_tool_calls,
    )

    return {"messages": [ai_response]}


# This node executes the tool call requested by the agent.
async def tool_executor_node(state: SubroutineState) -> Dict[str, List[BaseMessage]]:
    """
    Executes the tool call returned by the agent node.
    Validates tool arguments against the tool's expected schema.
    """
    print("\n⚙️  Executing tool...")
    last_message = state["messages"][-1]

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        tool_to_run = tool_executor_map.get(tool_name)
        if not tool_to_run:
            error_msg = f"Tool '{tool_name}' not found"
            print(f"   ❌ {error_msg}")
            return {"messages": [ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id)]}

        # Validate tool arguments against the tool's schema
        tool_schema = tool_to_run.input_schema
        required_params = tool_schema.get("required", [])
        schema_properties = tool_schema.get("properties", {})

        # Check for missing required parameters
        missing_params = [param for param in required_params if param not in tool_args]
        if missing_params:
            error_msg = f"Missing parameters: {missing_params}"
            print(f"   ❌ {error_msg}")
            return {"messages": [ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id)]}

        # Check for unexpected parameters
        unexpected_params = [param for param in tool_args.keys() if param not in schema_properties]
        if unexpected_params:
            print(f"   ⚠️  Ignoring unexpected parameters: {unexpected_params}")
            tool_args = {k: v for k, v in tool_args.items() if k in schema_properties}

        print(f"   ✓ Arguments validated")

        # Execute the tool
        try:
            result = await tool_to_run(**tool_args)
            print(f"   ✓ Result: {result}")
            return {
                "messages": [
                    ToolMessage(content=f"Tool Call Result: {result}", tool_call_id=tool_id)
                ]
            }
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            print(f"   ❌ {error_msg}")
            return {"messages": [ToolMessage(content=f"Error: {error_msg}", tool_call_id=tool_id)]}


# Conditional edge logic: decide where to go after the agent node.
def should_continue(state: SubroutineState) -> Literal["execute_tool", "__end__"]:
    last_message = state["messages"][-1]
    print("The Last Message:", last_message)
    if last_message.tool_calls:
        print("   → Routing to tool executor")
        return "execute_tool"
    print("   → Task complete, ending")
    return "__end__"


async def main():
    """Main function to set up and run the playground script."""
    print("\n" + "=" * 60)
    print("🚀 LangGraph + Ollama Tool Calling Playground")
    print("=" * 60)

    results = []

    try:
        await ollama_manager.on_start(mock_context.services)

        # 3. Create the Subroutine WITH the callback
        addition_subroutine = BaseSubroutine(
            name="OllamaAdditionAgent",
            description="An agent that uses a tool to add two numbers via Ollama.",
            input_schema={"properties": {"prompt": {"type": "string"}}},
            on_step_end=step_callback,
        )

        addition_subroutine.add_node("agent", agent_node)
        addition_subroutine.add_node("execute_tool", tool_executor_node)
        addition_subroutine.set_entry_point("agent")
        addition_subroutine.graph.add_conditional_edges(
            "agent", should_continue, {"execute_tool": "execute_tool", "__end__": "__end__"}
        )
        addition_subroutine.add_edge("execute_tool", "agent")
        addition_subroutine.set_finish_point(
            "agent"
        )  # Formality, end is handled by conditional edge

        # 4. Invoke the subroutine with a real question
        addition_subroutine.compile()

        import random

        a = random.random() * random.randint(-100, 100)
        b = random.randint(10, 2000)

        print(f"\n📝 Question: What is {a} + {b}?")
        print(f"📊 Expected: {a + b}\n")

        initial_state = {"messages": [HumanMessage(content=f"what is {a} + {b}?")]}

        # Add recursion limit to prevent infinite loops
        config = {"recursion_limit": 10}
        final_result = await addition_subroutine.ainvoke(initial_state, config=config)

        print("\n" + "=" * 60)
        _ = "\n".join([str(x) for x in final_result])
        print(f"✅ Final Answer: {_}")
        print(f"📊 Expected: {a + b}")
        print(f"✓ Correct: {str(a + b) in str(final_result)}")
        print("=" * 60)

    finally:
        await ollama_manager.on_close()


if __name__ == "__main__":
    # for i in range(10):
    asyncio.run(main())
