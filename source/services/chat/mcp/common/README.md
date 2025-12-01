# MCP Common Components

This directory contains common, reusable components for creating Model-Context-Protocol (MCP) tools and subroutines.

**Note**: Tool management has been migrated to FastMCP. Use the `MCPManager` in `../manager.py` for registering and managing tools.

## `langgraph_subroutine.py`

-   **`BaseSubroutine` Class**: A high-level wrapper for creating and managing `langgraph` workflows. It provides a structured interface for defining a graph of operations (nodes), setting entry/exit points, connecting them with edges, and executing the entire compiled subroutine with a given input.

## `utils.py`

-   **`convert_to_langchain_messages`**: A utility function that converts the project's custom `Message` objects into a list of standard `langchain_core.messages.BaseMessage` objects. This is a crucial compatibility layer that allows LangGraph subroutines to process existing conversation histories.

This module aims to streamline the development of new MCP components by handling boilerplate setup and providing clear, reusable patterns.
