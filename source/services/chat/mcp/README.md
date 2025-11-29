# Model-Context-Protocol (MCP) Components

This directory contains the core components for defining and managing MCP tools and subroutines, which allow an LLM to interact with external systems and execute complex, multi-step workflows.

## `subroutine_manager.py`

-   **`SubroutineManager` Class**: This is the central orchestrator for LangGraph subroutines. It registers `BaseSubroutine` objects and exposes them as context-aware tools for an LLM. It automatically handles fetching conversation history and passing it to the subroutine, bridging the gap between a simple tool call and a context-rich execution.

## `common/`

This subdirectory contains the foundational building blocks for the MCP system. See the `common/README.md` for more details on:
-   `BaseTool` and `@tool` decorator
-   `BaseSubroutine` class for LangGraph workflows
-   `utils.py` for message format conversion
