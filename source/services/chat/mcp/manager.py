"""
MCP Manager - Central tool registry and manager using FastMCP.

This manager provides a unified interface for registering, managing, and executing
tools for LLM interactions. It uses FastMCP as the underlying framework for tool
definition and management.

Key Features:
- Tool registration at startup using FastMCP
- Automatic schema generation from Python functions
- Conversion of MCP tools to Ollama-compatible format
- Tool execution with argument validation
- Integration with LangGraph subroutines
- Support for both regular tools and context-aware subroutines

Usage:
    # Initialize the manager
    mcp_manager = MCPManager(context=context)

    # Register tools at startup
    @mcp_manager.tool
    def search_database(query: str, limit: int = 10) -> dict:
        '''Search the database with the given query.'''
        return {"results": [...]}

    # Get tools for Ollama
    tools = mcp_manager.get_ollama_tools()

    # Execute a tool
    result = await mcp_manager.execute_tool("search_database", {"query": "test", "limit": 5})
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from fastmcp import FastMCP
from fastmcp.tools import Tool

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from source.services.manager import Manager


class MCPManager(Manager):
    """
    Central manager for MCP tools using FastMCP.

    This manager handles:
    - Tool registration and storage
    - Schema generation and management
    - Conversion to Ollama-compatible format
    - Tool execution with validation
    - Integration with subroutines
    """

    def __init__(self, context: Context):
        """
        Initialize the MCP Manager.

        Args:
            context: Application context
        """
        super().__init__(context)

        # Initialize FastMCP instance
        self._mcp = FastMCP(
            name="DiscordMeetingTranscriptor",
            on_duplicate_tools="warn",  # Warn but allow overwriting tools
        )

        # Track if tools have been registered
        self._tools_registered = False

    # -------------------------------------------------------------- #
    # Manager Lifecycle
    # -------------------------------------------------------------- #

    async def on_start(self, services: ServicesManager) -> None:
        """Actions to perform on manager start."""
        await super().on_start(services)
        if self.services:
            await self.services.logging_service.info("MCP Manager started")

    async def on_close(self) -> None:
        """Actions to perform on manager shutdown."""
        if self.services:
            tools = await self._mcp._tool_manager.get_tools()
            tool_count = len(tools)
            await self.services.logging_service.info(
                f"MCP Manager stopped (registered {tool_count} tools)"
            )

    # -------------------------------------------------------------- #
    # Tool Registration
    # -------------------------------------------------------------- #

    def tool(
        self,
        name_or_fn: str | Callable | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> Callable:
        """
        Decorator to register a tool with FastMCP.

        This provides a convenient way to register tools using the @mcp_manager.tool
        decorator pattern. The decorated function will be automatically registered
        with FastMCP, which handles schema generation and validation.

        Args:
            name_or_fn: Optional custom name for the tool or the function itself
            description: Optional description override
            **kwargs: Additional arguments passed to FastMCP's tool decorator

        Returns:
            Decorated function registered as a tool

        Example:
            @mcp_manager.tool
            def search(query: str, limit: int = 10) -> dict:
                '''Search the database.'''
                return {"results": [...]}
        """
        return self._mcp.tool(name_or_fn, **kwargs)

    def add_tool(self, tool: Tool) -> Tool:
        """
        Add an existing Tool object to the manager.

        Args:
            tool: FastMCP Tool instance

        Returns:
            The registered tool
        """
        return self._mcp.add_tool(tool)

    def add_tool_from_function(
        self,
        func: Callable,
        name: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> Tool:
        """
        Create and register a tool from a Python function.

        Args:
            func: The function to convert to a tool
            name: Optional custom name for the tool
            description: Optional description override
            **kwargs: Additional arguments for Tool.from_function

        Returns:
            The created and registered Tool
        """
        tool = Tool.from_function(
            fn=func,
            name=name,
            description=description,
            **kwargs,
        )
        return self.add_tool(tool)

    def remove_tool(self, name: str) -> bool:
        """
        Remove a tool by name.

        Args:
            name: The name of the tool to remove

        Returns:
            True if the tool was removed, False if not found
        """
        try:
            self._mcp.remove_tool(name)
            return True
        except (KeyError, ValueError):
            return False

    # -------------------------------------------------------------- #
    # Tool Access and Conversion
    # -------------------------------------------------------------- #

    async def get_all_tools(self) -> dict[str, Tool]:
        """
        Get all registered tools.

        Returns:
            Dictionary mapping tool names to Tool objects
        """
        return await self._mcp._tool_manager.get_tools()

    async def get_tool(self, name: str) -> Tool | None:
        """
        Get a specific tool by name.

        Args:
            name: The tool name

        Returns:
            The Tool object or None if not found
        """
        try:
            return await self._mcp._tool_manager.get_tool(name)
        except (KeyError, ValueError):
            return None

    async def has_tool(self, name: str) -> bool:
        """
        Check if a tool exists.

        Args:
            name: The tool name

        Returns:
            True if the tool exists
        """
        return await self._mcp._tool_manager.has_tool(name)

    async def get_mcp_tools(self) -> list[dict[str, Any]]:
        """
        Get all tools in MCP format.

        Returns:
            List of tool definitions in MCP format
        """
        tools = await self._mcp._tool_manager.get_tools()
        return [tool.to_mcp_tool().model_dump() for tool in tools.values()]

    async def get_ollama_tools(self) -> list[dict[str, Any]]:
        """
        Get all tools in Ollama-compatible format.

        Ollama expects tools in the format:
        {
            "type": "function",
            "function": {
                "name": "tool_name",
                "description": "tool description",
                "parameters": {
                    "type": "object",
                    "properties": {...},
                    "required": [...]
                }
            }
        }

        Returns:
            List of tool definitions in Ollama format
        """
        mcp_tools = await self.get_mcp_tools()
        ollama_tools = []

        for tool in mcp_tools:
            # Convert MCP format to Ollama format
            ollama_tool = {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {}),
                },
            }
            ollama_tools.append(ollama_tool)

        return ollama_tools

    # -------------------------------------------------------------- #
    # Tool Execution
    # -------------------------------------------------------------- #

    async def execute_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """
        Execute a tool by name with the given arguments.

        Args:
            name: The tool name
            arguments: Dictionary of arguments for the tool

        Returns:
            The tool's result

        Raises:
            ValueError: If the tool is not found
            Exception: If tool execution fails
        """
        tool = await self.get_tool(name)
        if not tool:
            raise ValueError(f"Tool '{name}' not found")

        arguments = arguments or {}

        try:
            # Execute the tool
            result = await tool.run(arguments=arguments)

            # Extract the actual result data
            # ToolResult may contain content blocks and structured data
            if hasattr(result, "to_mcp_result"):
                mcp_result = result.to_mcp_result()

                # If it's a CallToolResult, get the data
                if hasattr(mcp_result, "data"):
                    return mcp_result.data

                # If it's a tuple of (content_blocks, structured_data)
                if isinstance(mcp_result, tuple) and len(mcp_result) == 2:
                    return mcp_result[1]  # Return structured data

                # If it's just content blocks, extract text
                if isinstance(mcp_result, list):
                    text_parts = []
                    for block in mcp_result:
                        if hasattr(block, "text"):
                            text_parts.append(block.text)
                    return "\n".join(text_parts) if text_parts else None

            # Fallback: return the result as-is
            return result

        except Exception as e:
            if self.services:
                await self.services.logging_service.error(f"Error executing tool '{name}': {e}")
            raise

    # -------------------------------------------------------------- #
    # Statistics and Utilities
    # -------------------------------------------------------------- #

    async def get_statistics(self) -> dict[str, Any]:
        """
        Get statistics about registered tools.

        Returns:
            Dictionary with statistics
        """
        tools = await self.get_all_tools()

        # Count enabled/disabled tools
        enabled_count = sum(1 for tool in tools.values() if tool.enabled)
        disabled_count = len(tools) - enabled_count

        return {
            "total_tools": len(tools),
            "enabled_tools": enabled_count,
            "disabled_tools": disabled_count,
            "tool_names": list(tools.keys()),
        }

    @property
    def mcp(self) -> FastMCP:
        """Get the underlying FastMCP instance."""
        return self._mcp
