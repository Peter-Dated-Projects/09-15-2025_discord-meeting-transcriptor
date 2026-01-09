"""
Conversation Control Tool for managing bot monitoring behavior.

This tool allows the LLM to stop monitoring a channel/thread, which
prevents the bot from responding to messages until it's mentioned again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager


async def register_conversation_control_tools(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register conversation control tools with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """
    # No tools to register currently
    pass
