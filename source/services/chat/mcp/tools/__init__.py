"""
MCP Tools Package.

This package contains all tools registered with the MCP system.
"""

from source.services.chat.mcp.tools.discord_dm_tool import register_discord_tools
from source.services.chat.mcp.tools.google_tools import register_google_tools

__all__ = [
    "register_discord_tools",
    "register_google_tools",
]
