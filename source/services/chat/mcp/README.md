# Model-Context-Protocol (MCP) Components

This directory contains the core components for defining and managing MCP tools and subroutines, which allow an LLM to interact with external systems and execute complex, multi-step workflows.

## `manager.py`

-   **`MCPManager` Class**: Central manager for all MCP tools using FastMCP framework. Handles:
    -   Tool registration and storage using FastMCP
    -   Automatic schema generation from Python functions
    -   Conversion to Ollama-compatible tool format
    -   Tool execution with validation
    -   Integration with services and context

## `subroutine_manager/`

-   **`SubroutineManager` Class**: This is the orchestrator for LangGraph subroutines. It registers `BaseSubroutine` objects and exposes them as context-aware FastMCP tools for an LLM. It automatically handles fetching conversation history and passing it to the subroutine, bridging the gap between a simple tool call and a context-rich execution.

## `common/`

This subdirectory contains the foundational building blocks for the MCP system. See the `common/README.md` for more details on:
-   `BaseSubroutine` class for LangGraph workflows
-   `utils.py` for message format conversion

**Note**: The custom `BaseTool` and `@tool` decorator have been replaced by FastMCP's built-in tool management.
