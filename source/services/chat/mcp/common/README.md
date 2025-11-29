# MCP Common Tools

This directory contains `tool.py`, which defines the foundational components for creating Model-Context-Protocol (MCP) tools.

## `tool.py`

-   **`BaseTool` Class**: A versatile base class that wraps Python functions to turn them into MCP tools. It automatically generates the tool's name, description, and input schema from the function's signature, docstring, and type hints. It also incorporates access control mechanisms.
-   **`@tool` Decorator**: A convenient decorator for easily defining MCP tools. By decorating any Python function with `@tool()`, it is transformed into an MCP tool, simplifying tool registration and schema management.

This module aims to streamline the development of new MCP tools by handling boilerplate setup and schema generation.
