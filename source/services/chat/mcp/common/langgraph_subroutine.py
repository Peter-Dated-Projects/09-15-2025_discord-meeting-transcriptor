"""
This module provides a base class for creating LangGraph subroutines.

It encapsulates the setup and execution of a langgraph.StateGraph, allowing
for the structured definition of multi-step processes (subroutines) that can
be compiled and run with lifecycle hooks.
"""

import inspect
from typing import Annotated, Any, Callable, Dict, List, TypedDict, Union, Optional

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph

# Try importing add_messages from the top level (newer versions) or submodule (older versions)
try:
    from langgraph.graph import add_messages
except ImportError:
    from langgraph.graph.message import add_messages


class SubroutineState(TypedDict):
    """
    Represents the state of our subroutine graph.

    Attributes:
        messages: A list of LangChain BaseMessage objects.
                  Using `add_messages` ensures proper ID-based deduplication
                  and appending rather than simple list concatenation.
    """

    messages: Annotated[List[BaseMessage], add_messages]


class BaseSubroutine:
    """
    A base class for creating and managing LangGraph subroutines.

    This class provides a high-level interface to define a graph of operations
    (nodes), compile it, and execute it. It automatically wraps nodes to support
    step-by-step callbacks (`on_step_end`).
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        on_step_end: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        """
        Initializes the BaseSubroutine.

        Args:
            name (str): The name of the subroutine.
            description (str): A description of what the subroutine does.
            input_schema (Dict[str, Any]): JSON schema for input arguments.
            on_step_end (Callable, optional): A callback function triggered after
                each node execution. Can be sync or async.
        """
        self.name = name
        self.description = description
        self.input_schema = input_schema

        if on_step_end:
            self._validate_callback(on_step_end)
        self.on_step_end = on_step_end

        self._step_count = 0
        self.graph = StateGraph(SubroutineState)
        # Use Runnable as the type hint to avoid ImportError on specific Graph classes
        self._compiled_graph: Optional[Runnable] = None
        self._entry_point: Optional[str] = None

        # Track if we have manually set a path to END
        self._has_finish_point = False

    def _validate_callback(self, func: Callable) -> None:
        """Checks if the provided callback has a valid signature."""
        if not callable(func):
            raise TypeError("The provided 'on_step_end' callback must be a callable function.")

        sig = inspect.signature(func)
        # We allow flexible signatures (*args, **kwargs) or exactly 1 argument
        if len(sig.parameters) != 1 and not any(
            p.kind == p.VAR_KEYWORD for p in sig.parameters.values()
        ):
            raise TypeError(
                f"The 'on_step_end' callback function must accept one argument (step_info)."
            )

    def add_node(self, name: str, node_callable: Callable[[Any], Dict]):
        """
        Adds a node to the graph, wrapping it to support callbacks and async execution.

        Args:
            name (str): The unique name of the node.
            node_callable (Callable): The function for this node.
        """

        async def wrapper(state: Any) -> Dict:
            # 1. Execute the actual node logic
            if inspect.iscoroutinefunction(node_callable):
                result = await node_callable(state)
            else:
                result = node_callable(state)

            # 2. Trigger callback if defined
            if self.on_step_end:
                self._step_count += 1

                # Note: This is a rough approximation of the new state for the callback.
                # In LangGraph, the actual state merge happens *after* the node exits.
                # However, for logging purposes, merging the result dict is usually sufficient.
                current_state_snapshot = {**state, **(result if isinstance(result, dict) else {})}

                step_info = {
                    "step_name": name,
                    "step_count": self._step_count,
                    "subroutine_name": self.name,
                    "current_state": current_state_snapshot,
                    "node_output": result,
                }

                if inspect.iscoroutinefunction(self.on_step_end):
                    await self.on_step_end(step_info)
                else:
                    self.on_step_end(step_info)

            return result

        self.graph.add_node(name, wrapper)

    def set_entry_point(self, node_name: str):
        """Sets the entry point for the graph."""
        self.graph.add_edge(START, node_name)
        self._entry_point = node_name

    def set_finish_point(self, node_name: str):
        """Sets the finish point for the graph (connects node to END)."""
        self.graph.add_edge(node_name, END)
        self._has_finish_point = True

    def add_conditional_edges(self, source: str, path: Callable, path_map: Dict[str, str]):
        """Expose conditional edges wrapper."""
        self.graph.add_conditional_edges(source, path, path_map)

    def add_edge(self, start_node: str, end_node: str):
        """Adds a directed edge between two nodes."""
        self.graph.add_edge(start_node, end_node)

    def compile(self) -> Runnable:
        """Compiles the defined graph into a runnable object."""
        if self._entry_point is None:
            raise ValueError("An entry point must be set before compiling (use set_entry_point).")

        self._compiled_graph = self.graph.compile()
        return self._compiled_graph

    def invoke(self, initial_state: Dict) -> Optional[str]:
        """
        Sync execution of the graph.

        Returns:
            str: The content of the last message in the history.
        """
        self._step_count = 0
        if self._compiled_graph is None:
            self.compile()

        # Invoke the graph
        final_state = self._compiled_graph.invoke(initial_state)

        # Extract last message content (matching your original return signature)
        messages = final_state.get("messages", [])
        if messages and isinstance(messages, list):
            return messages[-1].content
        return None

    async def ainvoke(
        self, initial_state: Dict, config: Dict = None
    ) -> Optional[List[BaseMessage]]:
        """
        Async execution of the graph.

        Returns:
            List[BaseMessage]: The full history of messages.
        """
        self._step_count = 0
        if self._compiled_graph is None:
            self.compile()

        final_state = await self._compiled_graph.ainvoke(initial_state, config=config)

        messages = final_state.get("messages", [])
        if not messages:
            return None
        return messages
