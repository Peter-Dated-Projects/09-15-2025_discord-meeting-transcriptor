"""
This module provides a base class for creating LangGraph subroutines.

It encapsulates the setup and execution of a langgraph.StateGraph, allowing
for the structured definition of multi-step processes (subroutines) that can
be compiled and run.
"""

import operator
from typing import Annotated, Any, Callable, Dict, TypedDict

from langgraph.graph import END, StateGraph, CompiledGraph


class SubroutineState(TypedDict):
    """
    Represents the state of our subroutine graph.

    Attributes:
        input: The initial input dictionary for the subroutine.
        data: A dictionary to hold intermediate data passed between nodes.
        final_output: The final output from the designated end node.
    """

    input: Dict[str, Any]
    data: Annotated[Dict[str, Any], operator.add]
    final_output: Any


class BaseSubroutine:
    """
    A base class for creating and managing LangGraph subroutines.

    This class provides a high-level interface to define a graph of operations
    (nodes), compile it, and execute it with a given input.
    """

    def __init__(self, name: str, description: str):
        """
        Initializes the BaseSubroutine.

        Args:
            name (str): The name of the subroutine.
            description (str): A description of what the subroutine does.
        """
        self.name = name
        self.description = description

        self.graph = StateGraph(SubroutineState)
        self._compiled_graph: CompiledGraph | None = None
        self._entry_point: str | None = None
        self._finish_point: str | None = None

    def add_node(self, name: str, node_callable: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """
        Adds a node to the graph. Each node is a callable that processes the current
        state and returns an update.

        Args:
            name (str): The unique name of the node.
            node_callable (Callable): The function or callable to execute for this node.
                                      It should accept a state dictionary and return a
                                      dictionary to update the state.
        """
        self.graph.add_node(name, node_callable)

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
        Sets the finish point for the graph. When this node is reached, the graph
        will terminate by transitioning to the special END state.

        Args:
            node_name (str): The name of the node that should be the last one to execute.
        """
        self.graph.add_edge(node_name, END)
        self._finish_point = node_name

    def add_edge(self, start_node: str, end_node: str):
        """
        Adds a directed edge between two nodes, defining the execution flow.

        Args:
            start_node (str): The name of the node from which the edge originates.
            end_node (str): The name of the node where the edge terminates.
        """
        self.graph.add_edge(start_node, end_node)

    def compile(self) -> CompiledGraph:
        """
        Compiles the defined graph into a runnable object. This must be called
        after defining all nodes and edges.

        Returns:
            A compiled LangGraph instance.
        """
        if self._entry_point is None or self._finish_point is None:
            raise Exception("An entry point and a finish point must be set before compiling.")

        self._compiled_graph = self.graph.compile()
        return self._compiled_graph

    def invoke(self, initial_input: Dict[str, Any]) -> Any:
        """
        Runs the compiled subroutine with a given input.

        Args:
            initial_input (Dict[str, Any]): The initial input to pass to the graph's state.

        Returns:
            The final output from the subroutine's designated finish point.
        """
        if self._compiled_graph is None:
            print("Graph not compiled. Compiling now...")
            self.compile()

        if self._compiled_graph is None:
            raise Exception("Graph could not be compiled.")

        initial_state = {"input": initial_input, "data": {}}

        # The `invoke` method runs the graph from start to finish
        final_state = self._compiled_graph.invoke(initial_state)

        return final_state.get("final_output")
