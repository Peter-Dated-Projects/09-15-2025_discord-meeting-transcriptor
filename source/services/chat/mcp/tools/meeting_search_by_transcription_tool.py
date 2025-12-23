"""
Meeting Search by Transcription Tool.

This tool allows the bot to search for specific details within a meeting's transcript.
"""

from __future__ import annotations

import os
import json
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager

from source.services.chat.mcp.subroutine_manager.subroutines.meeting_search_by_transcription import (
    create_meeting_search_by_transcription_subroutine,
)


async def run_meeting_search_by_transcription_subroutine(meeting_id: str, query: str, context: Context) -> Any:
    """
    Run the meeting search by transcription subroutine.
    """
    if not context.services_manager:
        return "Error: Services manager not available"

    ollama_manager = context.services_manager.ollama_request_manager
    model = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:12b")

    # Create subroutine
    subroutine = create_meeting_search_by_transcription_subroutine(
        ollama_request_manager=ollama_manager, context=context, model=model
    )

    # Run subroutine
    try:
        # Pass arguments as JSON in the first message
        input_data = json.dumps({"meeting_id": meeting_id, "user_query": query})
        initial_state = {"messages": [HumanMessage(content=input_data)]}

        # Use ainvoke to run the graph
        result = await subroutine.ainvoke(initial_state)

        # The result is a list of messages.
        if not result:
            return "No results found."

        ollama_messages = []

        # Extract messages
        messages = result.get("messages", []) if isinstance(result, dict) else result

        for m in messages:
            if m.type == "ai":
                msg = {"role": "assistant", "content": m.content}
                if hasattr(m, "tool_calls") and m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "function": {
                                "name": tc.get("name"),
                                "arguments": tc.get("args"),
                            }
                        }
                        for tc in m.tool_calls
                    ]
                ollama_messages.append(msg)
            elif m.type == "tool":
                ollama_messages.append({"role": "tool", "content": m.content})
            elif m.type == "human":
                # We can skip the input JSON message to keep history clean
                pass
            elif m.type == "system":
                ollama_messages.append({"role": "system", "content": m.content})

        return ollama_messages
    except Exception as e:
        if context.services_manager.logging_service:
            await context.services_manager.logging_service.error(
                f"Error running meeting search by transcription subroutine: {e}"
            )
        return f"Error: {str(e)}"


async def register_meeting_search_by_transcription_tool(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register the Meeting Search by Transcription tool with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """

    # Create a closure that captures the context
    async def search_meetings_by_transcription_tool(meeting_id: str, query: str) -> Any:
        """
        Search for specific details within a meeting's transcript.
        Useful for answering questions like "What did they say about X in meeting Y?".

        Args:
            meeting_id: The ID of the meeting to search.
            query: The specific question or topic to search for within the meeting.
        """
        return await run_meeting_search_by_transcription_subroutine(meeting_id, query, context)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=search_meetings_by_transcription_tool,
        name="search_meetings_by_transcription",
        description="Search for specific details within a meeting's transcript. Returns relevant segments and an answer.",
    )

    # Log registration
    if context.services_manager and context.services_manager.logging_service:
        await context.services_manager.logging_service.info(
            "[MCP] Registered Meeting Search by Transcription tool: search_meetings_by_transcription"
        )
