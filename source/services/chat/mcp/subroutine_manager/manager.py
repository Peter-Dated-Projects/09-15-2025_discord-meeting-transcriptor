"""
This module defines the SubroutineManager, a class responsible for managing
LangGraph subroutines and exposing them as callable, context-aware tools for an LLM.

Updated to work with FastMCP instead of the custom BaseTool implementation.
"""

import functools
from typing import Any, Dict, List

from langchain_core.messages import AIMessage
from fastmcp.tools import Tool

# Adjust imports based on actual project structure
from source.services.chat.conversation_manager.in_memory_cache import (
    InMemoryConversationManager,
)
from source.services.chat.mcp.common.langgraph_subroutine import BaseSubroutine
from source.services.chat.mcp.common.utils import convert_to_langchain_messages


class SubroutineManager:
    """
    Manages LangGraph subroutines and exposes them as context-aware tools.

    This manager connects to a conversation manager to fetch chat history.
    When a subroutine is added, it creates a proxy tool that requires a `thread_id`,
    allowing the subroutine to be executed with the full context of the conversation.
    """

    def __init__(self, conversation_manager: InMemoryConversationManager):
        """
        Initializes the SubroutineManager.

        Args:
            conversation_manager: An instance of InMemoryConversationManager to
                                  retrieve conversation context.
        """
        self._conversation_manager = conversation_manager
        self._subroutines: Dict[str, BaseSubroutine] = {}
        self._tools: Dict[str, Tool] = {}

    def _execute_subroutine_with_context(
        self, subroutine_name: str, thread_id: str, tool_kwargs: Dict[str, Any]
    ):
        """
        The core execution logic that retrieves context and runs a subroutine.
        """
        subroutine = self._subroutines.get(subroutine_name)
        if not subroutine:
            raise ValueError(f"Subroutine '{subroutine_name}' not found.")

        # 1. Fetch conversation history
        conversation = self._conversation_manager.get_conversation(thread_id)
        history = conversation.history if conversation else []

        # 2. Convert to LangChain messages
        langchain_messages = convert_to_langchain_messages(history)

        # 3. Append the current tool call to the message history
        # This lets the subroutine know what tool was just called and with what arguments.
        # We simulate the AI's tool-calling turn.
        tool_call_id = tool_kwargs.pop("tool_call_id", f"call_{subroutine_name}")
        langchain_messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": subroutine.name,
                        "args": tool_kwargs,
                        "id": tool_call_id,
                    }
                ],
            )
        )

        # 4. Invoke the subroutine with the prepared state
        initial_state = {"messages": langchain_messages}
        return subroutine.invoke(initial_state)

    async def _execute_subroutine_with_context_async(
        self, subroutine_name: str, thread_id: str, tool_kwargs: Dict[str, Any]
    ):
        """
        Async version of execute_subroutine_with_context for FastMCP compatibility.
        """
        subroutine = self._subroutines.get(subroutine_name)
        if not subroutine:
            raise ValueError(f"Subroutine '{subroutine_name}' not found.")

        # 1. Fetch conversation history
        conversation = self._conversation_manager.get_conversation(thread_id)
        history = conversation.history if conversation else []

        # 2. Convert to LangChain messages
        langchain_messages = convert_to_langchain_messages(history)

        # 3. Append the current tool call to the message history
        tool_call_id = tool_kwargs.pop("tool_call_id", f"call_{subroutine_name}")
        langchain_messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": subroutine.name,
                        "args": tool_kwargs,
                        "id": tool_call_id,
                    }
                ],
            )
        )

        # 4. Invoke the subroutine with the prepared state
        initial_state = {"messages": langchain_messages}

        # Use ainvoke if available, otherwise fall back to invoke
        if hasattr(subroutine, "ainvoke"):
            return await subroutine.ainvoke(initial_state)
        else:
            return subroutine.invoke(initial_state)

    def add_subroutine(
        self,
        subroutine: BaseSubroutine,
        allow_write: bool = None,
        allow_sensitive_data_access: bool = None,
    ):
        """
        Adds a subroutine and creates a context-aware proxy tool for it.

        The generated tool will automatically include a `thread_id: str` parameter
        in addition to the parameters defined in the subroutine's `input_schema`.
        """
        if subroutine.name in self._subroutines:
            print(f"Warning: Subroutine '{subroutine.name}' will be overwritten.")

        self._subroutines[subroutine.name] = subroutine

        # Create a wrapper function for the subroutine execution
        # This will be converted to a tool by FastMCP
        async def subroutine_tool_wrapper(
            thread_id: str,
            **tool_kwargs: Any,
        ) -> Any:
            """
            Execute the subroutine with conversation context.

            Args:
                thread_id: The active conversation thread ID
                **tool_kwargs: Additional arguments specific to the subroutine
            """
            return await self._execute_subroutine_with_context_async(
                subroutine.name,
                thread_id,
                tool_kwargs,
            )

        # Create a tool from the wrapper function
        # FastMCP will handle schema generation from type hints
        tool = Tool.from_function(
            fn=subroutine_tool_wrapper,
            name=subroutine.name,
            description=subroutine.description,
        )

        self._tools[tool.name] = tool
        print(f"Subroutine '{subroutine.name}' added and context-aware tool created.")

    def get_tools(self) -> List[Tool]:
        """Returns a list of all generated tool objects."""
        return list(self._tools.values())

    def get_tool_schemas(self) -> List[Dict]:
        """Returns a list of the JSON schemas for all managed tools."""
        return [tool.to_mcp_tool().model_dump() for tool in self.get_tools()]

    @property
    def tools(self) -> Dict[str, Tool]:
        return self._tools
