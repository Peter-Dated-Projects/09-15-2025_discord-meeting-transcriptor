"""
Playground for testing LangGraph subroutines with MCP components.
"""

import asyncio
from typing import Annotated, Any, Dict, List, Literal, TypedDict
import operator

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# --- Import MCP Components ---
# Note: Adjust these imports based on your project's PYTHONPATH setup.
# For a standalone script, you might need to add the project root to sys.path.
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from source.services.chat.mcp.common.tool import BaseTool
from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.gpu.gpu_resource_manager.manager import GPUResourceManager


# --- Mock Application Context for GPU Manager ---
# The GPUResourceManager requires context and services for logging.
# We'll create minimal mock objects to satisfy these dependencies.


class MockLoggingService:
    async def info(self, msg: str):
        print(f"[INFO] {msg}")

    async def error(self, msg: str):
        print(f"[ERROR] {msg}")


class MockServices:
    def __init__(self):
        self.logging_service = MockLoggingService()


class MockContext:
    def __init__(self):
        self.services = MockServices()
        self.server_manager = None


# --- 1. Define a simple tool and a callback function ---


def add(a: int, b: int) -> int:
    """Adds two numbers."""
    print(f"\n--- Tool: 'add' called with a={a}, b={b} ---")
    return a + b


add_tool = BaseTool(func=add)
tools = {"add": add_tool}


def step_callback(step_info: dict):
    """A simple callback to print the details of each step."""
    print("\n=========================================")
    print(f"| Subroutine: {step_info['subroutine_name']}")
    print(f"| Step {step_info['step_count']}: {step_info['step_name']}")
    print("-----------------------------------------")
    last_message = step_info["current_state"]["messages"][-1]
    print(f"| Step Output: {last_message.pretty_repr()}")
    print("=========================================")


# --- 2. Define the Agentic Workflow (as a Subroutine) ---


# This node simulates an LLM deciding what to do.
def agent_node(state: SubroutineState) -> Dict[str, List[BaseMessage]]:
    """
    Agent node that decides whether to call a tool or finish.
    In a real app, this would involve an LLM call.
    """
    print("\n--- Agent Node Logic Executing ---")
    last_message = state["messages"][-1]

    # If the last message was a tool result, formulate a final answer.
    if isinstance(last_message, ToolMessage):
        final_answer = f"The result of the addition is {last_message.content}."
        print(f"Agent: Saw tool result, formulating final answer.")
        return {"messages": [AIMessage(content=final_answer)]}

    # If it's a human message, decide to call the 'add' tool.
    # We are hardcoding the tool call for this example.
    print("Agent: Saw human input, deciding to call the 'add' tool.")
    tool_call = {
        "name": "add",
        "args": {"a": 5, "b": 7},
        "id": "call_add_123",
    }
    return {"messages": [AIMessage(content="", tool_calls=[tool_call])]}


# This node executes the tool call requested by the agent.
def tool_executor_node(state: SubroutineState) -> Dict[str, List[BaseMessage]]:
    """
    Executes the tool call requested by the agent node.
    """
    print("\n--- Tool Executor Node Logic Executing ---")
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]

    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    tool_id = tool_call["id"]

    tool_to_run = tools.get(tool_name)
    if not tool_to_run:
        raise ValueError(f"Tool '{tool_name}' not found.")

    # We need to use asyncio.run for the __call__ since it's async
    result = asyncio.run(tool_to_run(**tool_args))

    return {"messages": [ToolMessage(content=str(result), tool_call_id=tool_id)]}


# Conditional edge logic: decide where to go after the agent node.
def should_continue(state: SubroutineState) -> Literal["execute_tool", "__end__"]:
    """Determines the next step after the agent node runs."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        print("Agent has decided to use a tool. -> Routing to tool executor.")
        return "execute_tool"
    print("Agent has provided the final answer. -> Routing to END.")
    return "__end__"


async def main():
    """Main function to set up and run the playground script."""
    print("Initializing mock context and GPU manager...")
    mock_context = MockContext()
    gpu_manager = GPUResourceManager(context=mock_context)
    # The manager's scheduler starts on its own in a real app via `on_start`.
    # For this script, we don't need to start it as we are not using the priority queue.

    print("\nAttempting to acquire GPU lock...")
    # Use the GPU manager to acquire a lock for a 'chatbot' type job
    async with gpu_manager.acquire_lock(job_type="chatbot"):
        print("\nGPU Lock Acquired. Starting LangGraph workflow...")

        # 3. Create the Subroutine WITH the callback
        addition_subroutine = BaseSubroutine(
            name="AdditionAgent",
            description="An agent that uses a tool to add two numbers.",
            input_schema={"properties": {"prompt": {"type": "string"}}},
            on_step_end=step_callback,  # <-- Register the callback here
        )

        addition_subroutine.add_node("agent", agent_node)
        addition_subroutine.add_node("execute_tool", tool_executor_node)

        addition_subroutine.set_entry_point("agent")

        # Add the conditional edge
        addition_subroutine.graph.add_conditional_edges(
            "agent",
            should_continue,
            {
                "execute_tool": "execute_tool",
                "__end__": "__end__",
            },
        )

        # Add the edge back from the tool executor to the agent
        addition_subroutine.add_edge("execute_tool", "agent")

        # It's important to set a finish point, even if conditional logic points to END.
        # This is a formality for the graph structure.
        addition_subroutine.set_finish_point("agent")

        # 4. Manually invoke the subroutine
        print("\nCompiling and invoking the subroutine manually...")
        addition_subroutine.compile()

        initial_state = {"messages": [HumanMessage(content="What is 5 + 7?")]}

        final_result = addition_subroutine.invoke(initial_state)

        print("\n-----------------------------------------")
        print(f"Subroutine finished with final result: '{final_result}'")
        print("-----------------------------------------")

    print("\nGPU Lock Released.")


if __name__ == "__main__":
    asyncio.run(main())
