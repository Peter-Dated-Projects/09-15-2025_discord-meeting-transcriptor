"""
MCP Tools Package.

This package contains all tools registered with the MCP system.
"""

from source.services.chat.mcp.tools.discord_dm_tool import register_discord_tools
from source.services.chat.mcp.tools.discord_info_tools import register_discord_info_tools
from source.services.chat.mcp.tools.google_tools import register_google_tools
from source.services.chat.mcp.tools.meeting_search_by_summary_tool import (
    register_meeting_search_by_summary_tool,
)
from source.services.chat.mcp.tools.meeting_search_by_transcription_tool import (
    register_meeting_search_by_transcription_tool,
)

__all__ = [
    "register_discord_tools",
    "register_discord_info_tools",
    "register_google_tools",
    "register_meeting_search_by_summary_tool",
    "register_meeting_search_by_transcription_tool",
]
