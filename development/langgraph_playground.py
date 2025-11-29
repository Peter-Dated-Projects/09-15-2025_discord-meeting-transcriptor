"""
Playground for testing LangGraph subroutines with a real Ollama LLM call.
"""

import asyncio
from typing import Any, Dict, List, Literal
import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

# --- Import MCP Components ---
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from source.services.chat.mcp.common.tool import BaseTool
from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.gpu.ollama_request_manager.manager import OllamaRequestManager


# --- Mock Application Context for Ollama Manager ---
class MockLoggingService:
    async def info(self, msg: str): print(f"[INFO] {msg}")
    async def error(self, msg: str): print(f"[ERROR] {msg}")
    async def debug(self, msg: str): print(f"[DEBUG] {msg}")
    async def warning(self, msg: str): print(f"[WARN] {msg}")

class MockServices:
    def __init__(self): self.logging_service = MockLoggingService()

class MockContext:
    def __init__(self):
        self.services = MockServices()
        self.server_manager = None

# --- Global instances for the playground ---
mock_context = MockContext()
ollama_manager = OllamaRequestManager(context=mock_context)

# --- 1. Define a simple tool and a callback function ---

def add(a: int, b: int) -> int:
    """Adds two numbers.
    Args:
        a (int): The first number.
        b (int): The second number.
    """
    print(f"\n--- Tool: 'add' called with a={a}, b={b} ---")
    return a + b

add_tool = BaseTool(func=add)
# The executor needs a map of tool names to tool objects
tool_executor_map = {"add": add_tool}

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

def convert_lc_messages_to_ollama(messages: List[BaseMessage]) -> List[Dict]:
    """Converts LangChain messages to the dict format OllamaRequestManager expects."""
    ollama_msgs = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            ollama_msgs.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            # We don't include the tool calls here as they are passed separately
            ollama_msgs.append({"role": "assistant", "content": msg.content})
    return ollama_msgs

# This node now makes a real LLM call
async def agent_node(state: SubroutineState) -> Dict[str, List[BaseMessage]]:
    """
    Calls the Ollama model with the current state and a tool, then returns
    the model's response as an AIMessage.
    """
    print("\n--- Agent Node Logic Executing: Calling Ollama ---")
    
    # Get the schema of the 'add' tool for the LLM
    add_tool_schema = add_tool.to_mcp_schema()

    # Convert LangChain message history to the format Ollama manager needs
    ollama_messages = convert_lc_messages_to_ollama(state["messages"])

    # Define a system prompt to encourage tool use
    system_prompt = (
        "You are a helpful assistant. You must use the provided tools to answer "
        "questions whenever possible. If you need to perform addition, use the 'add' tool."
    )

    # Call the Ollama manager
    response = await ollama_manager.query(
        model="gpt-oss:20b",
        messages=ollama_messages,
        system_prompt=system_prompt,
        tools=[add_tool_schema],
        stream=False,
    )

    # Wrap the response in an AIMessage for the graph state
    ai_response = AIMessage(
        content=response.content,
        tool_calls=response.tool_calls or [],
    )
    
    return {"messages": [ai_response]}

# This node executes the tool call requested by the agent.
async def tool_executor_node(state: SubroutineState) -> Dict[str, List[BaseMessage]]:
    """
    Executes the tool call returned by the agent node.
    """
    print("\n--- Tool Executor Node Logic Executing ---")
    last_message = state["messages"][-1]
    tool_call = last_message.tool_calls[0]
    
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    tool_id = tool_call["id"]

    tool_to_run = tool_executor_map.get(tool_name)
    if not tool_to_run:
        raise ValueError(f"Tool '{tool_name}' not found.")

    result = await tool_to_run(**tool_args)
    
    return {"messages": [ToolMessage(content=str(result), tool_call_id=tool_id)]}

# Conditional edge logic: decide where to go after the agent node.
def should_continue(state: SubroutineState) -> Literal["execute_tool", "__end__"]:
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        print("Agent has decided to use a tool. -> Routing to tool executor.")
        return "execute_tool"
    print("Agent has provided the final answer. -> Routing to END.")
    return "__end__"


async def main():
    """Main function to set up and run the playground script."""
    print("Initializing Ollama Request Manager...")
    
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
        addition_subroutine.set_finish_point("agent") # Formality, end is handled by conditional edge

        # 4. Invoke the subroutine with a real question
        print("\nCompiling and invoking the subroutine...")
        addition_subroutine.compile()

        initial_state = {"messages": [HumanMessage(content="what is 10 + 10")]}
        final_result = await addition_subroutine.ainvoke(initial_state)

        print("\n-----------------------------------------")
        print(f"Subroutine finished with final result: '{final_result}'")
        print("-----------------------------------------")
    
    finally:
        print("\nClosing Ollama Request Manager...")
        await ollama_manager.on_close()


if __name__ == "__main__":
    # Make sure your Ollama server is running and has the 'gpt-oss:20b' model
    print("Please ensure your Ollama server is running and has the 'gpt-oss:20b' model available.")
    asyncio.run(main())
