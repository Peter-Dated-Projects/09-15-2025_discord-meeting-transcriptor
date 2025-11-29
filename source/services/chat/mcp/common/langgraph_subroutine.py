"""
This module provides a base class for creating LangGraph subroutines.

It encapsulates the setup and execution of a langgraph.StateGraph, allowing
for the structured definition of multi-step processes (subroutines) that can
be compiled and run.
"""

import operator
import inspect
from typing import Annotated, Any, Callable, Dict, List, TypedDict

from langgraph.graph import END
from langgraph.graph.state import StateGraph, CompiledStateGraph
from langchain_core.messages import BaseMessage


class SubroutineState(TypedDict):
    """
    Represents the state of our subroutine graph, centered around a list of messages.

    Attributes:
        messages: A list of LangChain BaseMessage objects that the graph will
                  process and add to. The `operator.add` annotation tells
                  LangGraph to append new messages to this list.
    """

    messages: Annotated[List[BaseMessage], operator.add]


class BaseSubroutine:
    """
    A base class for creating and managing LangGraph subroutines.

    This class provides a high-level interface to define a graph of operations
    (nodes), compile it, and execute it with a given initial state. It also
    supports an optional callback that is triggered after each step.
    """

    def __init__(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        on_step_end: Callable[[Dict[str, Any]], None] = None,
    ):
        """
        Initializes the BaseSubroutine.

        Args:
            name (str): The name of the subroutine.
            description (str): A description of what the subroutine does.
            input_schema (Dict[str, Any]): A JSON schema defining the arguments
                this subroutine expects from an LLM tool call.
            on_step_end (Callable[[Dict[str, Any]], None], optional): An optional
                callback function to be called after each node execution.
        """
        self.name = name
        self.description = description
        self.input_schema = input_schema

        if on_step_end:
            self._validate_callback(on_step_end)
        self.on_step_end = on_step_end

        self._step_count = 0
        self.graph = StateGraph(SubroutineState)
        self._compiled_graph: CompiledStateGraph | None = None
        self._entry_point: str | None = None
        self._finish_point: str | None = None

    def _validate_callback(self, func: Callable) -> None:
        """Checks if the provided callback has a valid signature."""
        if not callable(func):
            raise TypeError("The provided 'on_step_end' callback must be a callable function.")

        sig = inspect.signature(func)
        if len(sig.parameters) != 1:
            raise TypeError(
                f"The 'on_step_end' callback function must accept exactly one argument, "
                f"but it accepts {len(sig.parameters)}."
                "\nExpected signature: `def my_callback(step_info: dict): ...`"
            )

    def add_node(self, name: str, node_callable: Callable[[SubroutineState], Dict]):
        """
        Adds a node to the graph, wrapping it to support callbacks and async.

        Args:
            name (str): The unique name of the node.
            node_callable (Callable): The sync or async function for this node.
        """

        async def wrapper(state: SubroutineState) -> Dict:
            # Execute the original node logic, awaiting if it's async
            if inspect.iscoroutinefunction(node_callable):
                result = await node_callable(state)
            else:
                result = node_callable(state)

            # After execution, trigger the callback if it exists
            if self.on_step_end:
                self._step_count += 1
                # The new state is the current state merged with the node's output
                new_state = {**state, **result}

                step_info = {
                    "step_name": name,
                    "step_count": self._step_count,
                    "subroutine_name": self.name,
                    "current_state": new_state,
                }
                # If the on_step_end callback is async, await it.
                if inspect.iscoroutinefunction(self.on_step_end):
                    await self.on_step_end(step_info)
                else:
                    self.on_step_end(step_info)

            return result

        self.graph.add_node(name, wrapper)

    def set_entry_point(self, node_name: str):
        """
        Sets the entry point for the graph.
        Args:
            node_name (str): The name of the node that should execute first.
        """
        self.graph.set_entry_point(node_name)
        self._entry_point = node_name

    def set_finish_point(self, node_name: str):
        """
        Sets the finish point for the graph.
        Args:
            node_name (str): The name of the node that should be the last one to execute.
        """
        self.graph.add_edge(node_name, END)
        self._finish_point = node_name

    def add_edge(self, start_node: str, end_node: str):
        """
        Adds a directed edge between two nodes.
        Args:
            start_node (str): The name of the node from which the edge originates.
            end_node (str): The name of the node where the edge terminates.
        """
        self.graph.add_edge(start_node, end_node)

    def compile(self) -> CompiledStateGraph:
        """
        Compiles the defined graph into a runnable object.
        Returns:
            A compiled LangGraph instance.
        """
        if self._entry_point is None or self._finish_point is None:
            raise Exception("An entry point and a finish point must be set before compiling.")
        self._compiled_graph = self.graph.compile()
        return self._compiled_graph

    def invoke(self, initial_state: Dict) -> Any:
        """
        Runs the compiled subroutine with a given initial state.

        Args:
            initial_state (Dict): The initial state to pass to the graph.

        Returns:
            The content of the last message in the graph's final state.
        """
        # Reset step counter for each invocation
        self._step_count = 0

        if self._compiled_graph is None:
            print("Graph not compiled. Compiling now...")
            self.compile()

        if self._compiled_graph is None:
            raise Exception("Graph could not be compiled.")

        final_state = self._compiled_graph.invoke(initial_state)

        final_messages = final_state.get("messages", [])
        if not final_messages:
            return None
        return final_messages[-1].content

    async def ainvoke(self, initial_state: Dict, config: Dict = None) -> Any:
        """
        Asynchronously runs the compiled subroutine with a given initial state.

        Args:
            initial_state (Dict): The initial state to pass to the graph.
            config (Dict, optional): Configuration options for the graph execution,
                such as recursion_limit.

        Returns:
            The content of the last message in the graph's final state.
        """
        # Reset step counter for each invocation
        self._step_count = 0

        if self._compiled_graph is None:
            print("Graph not compiled. Compiling now...")
            self.compile()

        if self._compiled_graph is None:
            raise Exception("Graph could not be compiled.")

        final_state = await self._compiled_graph.ainvoke(initial_state, config=config)

        final_messages = final_state.get("messages", [])
        if not final_messages:
            return None
        return final_messages[-1].content
