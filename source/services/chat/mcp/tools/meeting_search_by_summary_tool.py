"""
Meeting Search by Summary Tool.

This tool allows the bot to search for past meetings using the meeting search by summary subroutine.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager

from source.services.chat.mcp.subroutine_manager.subroutines.meeting_search_by_summary import (
    create_meeting_search_by_summary_subroutine,
)


async def run_meeting_search_by_summary_subroutine(query: str, context: Context) -> Any:
    """
    Run the meeting search by summary subroutine to find and summarize meetings.
    """
    if not context.services_manager:
        return "Error: Services manager not available"

    ollama_manager = context.services_manager.ollama_request_manager
    model = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:12b")

    # Create subroutine
    subroutine = create_meeting_search_by_summary_subroutine(
        ollama_request_manager=ollama_manager, context=context, model=model
    )

    # Run subroutine
    try:
        # The input state expects "messages"
        initial_state = {"messages": [HumanMessage(content=query)]}
        # Use ainvoke to run the graph
        result = await subroutine.ainvoke(initial_state)

        # The result is a list of messages.
        if not result:
            return "No results found."

        # We return the raw messages list (or serialized version)
        # The ChatJobManager is now capable of handling list of messages
        # and injecting them into the conversation history.

        ollama_messages = []
        # The result["messages"] contains the full history of the subroutine
        # We want to return this to the main chat loop.

        # If result is a dict with "messages", extract it
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
                # We generally don't need to return the human message that started it
                # as it's already in the main history, but for completeness of the subroutine trace:
                ollama_messages.append({"role": "user", "content": m.content})
            elif m.type == "system":
                ollama_messages.append({"role": "system", "content": m.content})

        return ollama_messages
    except Exception as e:
        if context.services_manager.logging_service:
            await context.services_manager.logging_service.error(
                f"Error running meeting search by summary subroutine: {e}"
            )
        return f"Error: {str(e)}"


async def register_meeting_search_by_summary_tool(
    mcp_manager: MCPManager, context: Context
) -> None:
    """
    Register the Meeting Search by Summary tool with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """

    # Create a closure that captures the context
    async def search_meetings_by_summary_tool(query: str) -> Any:
        """
        Search for past meetings based on a query using summaries.
        Returns meeting IDs and relevant summary snippets.

        Args:
            query: The search query (e.g., "budget discussion", "project alpha launch").
        """
        return await run_meeting_search_by_summary_subroutine(query, context)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=search_meetings_by_summary_tool,
        name="search_meetings_by_summary",
        description="Search the database of past meeting summaries for relevant discussions. Returns meeting IDs and summary snippets. Best for short and quick general queries.",
    )

    # Log registration
    if context.services_manager and context.services_manager.logging_service:
        await context.services_manager.logging_service.info(
            "[MCP] Registered Meeting Search by Summary tool: search_meetings_by_summary"
        )
