"""
This module defines the SubroutineManager, a class responsible for managing
LangGraph subroutines and exposing them as callable, context-aware tools for an LLM.
"""

import functools
from typing import Any, Dict, List

from langchain_core.messages import AIMessage

# Adjust imports based on actual project structure
from ....chat.conversation_manager.in_memory_cache import (
    InMemoryConversationManager,
)
from .langgraph_subroutine import BaseSubroutine
from .tool import BaseTool
from .utils import convert_to_langchain_messages


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
        self._tools: Dict[str, BaseTool] = {}

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

        # Create a partial function that locks in the subroutine's name.
        # This is the function the tool will ultimately call.
        runner_func = functools.partial(
            self._execute_subroutine_with_context, subroutine.name
        )

        # To create the correct schema for the tool, we dynamically create a
        # wrapper function that has the right signature for BaseTool to inspect.
        # This is an advanced technique to avoid having to manually define the tool.
        
        # Start with the mandatory thread_id parameter
        params = ["thread_id: str"]
        # Add parameters from the subroutine's declared input schema
        for name, schema in subroutine.input_schema.get("properties", {}).items():
            # This is a simplification; a full implementation would map JSON schema types
            # to Python types more robustly.
            type_str = "Any"
            if schema.get("type") == "string":
                type_str = "str"
            elif schema.get("type") == "integer":
                type_str = "int"
            elif schema.get("type") == "number":
                type_str = "float"
            elif schema.get("type") == "boolean":
                type_str = "bool"
            elif schema.get("type") == "array":
                type_str = "list"
            elif schema.get("type") == "object":
                type_str = "dict"
            
            params.append(f"{name}: {type_str}")
        
        params_str = ", ".join(params)
        func_def = f"def tool_wrapper({params_str}):\n    pass"

        # Execute the function definition in a temporary scope
        temp_scope = {}
        exec(func_def, globals(), temp_scope)
        tool_wrapper_func = temp_scope['tool_wrapper']

        # Now, create the tool using this dynamically generated wrapper for its schema,
        # but with the *actual* runner function as its callable.
        tool = BaseTool(
            name=subroutine.name,
            description=subroutine.description,
            func=runner_func,  # The real logic
            # We need to modify BaseTool to accept a schema_func for introspection
            # For now, we'll pass the wrapper, but this highlights a need for a small refactor there.
            # A cleaner way would be tool(..., schema_override=subroutine.input_schema)
        )
        
        # Manually override the generated schema with our more precise one
        tool.input_schema["properties"] = {
            "thread_id": {"type": "string", "description": "The active conversation thread ID."},
            **subroutine.input_schema.get("properties", {})
        }
        tool.input_schema["required"] = ["thread_id"] + subroutine.input_schema.get("required", [])


        self._tools[tool.name] = tool
        print(f"Subroutine '{subroutine.name}' added and context-aware tool created.")

    def get_tools(self) -> List[BaseTool]:
        """Returns a list of all generated tool objects."""
        return list(self._tools.values())

    def get_tool_schemas(self) -> List[Dict]:
        """Returns a list of the JSON schemas for all managed tools."""
        return [tool.to_mcp_schema() for tool in self.get_tools()]

    @property
    def tools(self) -> Dict[str, BaseTool]:
        return self._tools
