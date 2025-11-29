# MCP Common Components

This directory contains common, reusable components for creating Model-Context-Protocol (MCP) tools and subroutines.

## `tool.py`

-   **`BaseTool` Class**: A versatile base class that wraps Python functions to turn them into MCP tools. It automatically generates the tool's name, description, and input schema from the function's signature, docstring, and type hints. It also incorporates access control mechanisms.
-   **`@tool` Decorator**: A convenient decorator for easily defining MCP tools. By decorating any Python function with `@tool()`, it is transformed into an MCP tool, simplifying tool registration and schema management.

## `langgraph_subroutine.py`

-   **`BaseSubroutine` Class**: A high-level wrapper for creating and managing `langgraph` workflows. It provides a structured interface for defining a graph of operations (nodes), setting entry/exit points, connecting them with edges, and executing the entire compiled subroutine with a given input. This simplifies the creation of complex, multi-step agents and processes.

This module aims to streamline the development of new MCP components by handling boilerplate setup and providing clear, reusable patterns.
