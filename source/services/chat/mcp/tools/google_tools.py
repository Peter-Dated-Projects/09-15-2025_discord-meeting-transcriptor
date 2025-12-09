"""
Google Query Tool for using Google Custom Search API.

This tool allows the bot to perform Google searches and retrieve relevant information.
"""

from __future__ import annotations

import os
import asyncio
from typing import TYPE_CHECKING, List
from googleapiclient.discovery import build

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager


async def query_google(queries: List[str], context: Context) -> dict:
    """
    Perform a Google search using the provided query strings.

    Args:
        queries: The search query strings
        context: Application context for accessing the bot

    Returns:
        dict with search results or error message

    """
    api_key = os.getenv("GCP_CUSTOM_SEARCH_API_KEY")
    cse_id = os.getenv("GCP_PROGRAMMABLE_SEARCH_ENGINE_CX")

    if not api_key or not cse_id:
        return {"error": "Google Search API key or CSE ID not configured."}

    results = {}

    def _search(query):
        service = build("customsearch", "v1", developerKey=api_key)
        res = service.cse().list(q=query, cx=cse_id, num=5).execute()
        return res.get("items", [])

    for query in queries:
        try:
            # Run blocking search in a thread
            items = await asyncio.to_thread(_search, query)
            formatted_results = []
            for item in items:
                formatted_results.append(
                    {
                        "title": item.get("title"),
                        "link": item.get("link"),
                        "snippet": item.get("snippet"),
                    }
                )
            results[query] = formatted_results
        except Exception as e:
            results[query] = {"error": str(e)}

    return {"results": results}


async def register_google_tools(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register Google Search tools with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """

    # Create a closure that captures the context
    async def google_search_tool(queries: List[str]) -> dict:
        """
        Perform a Google search to find information on the web.

        Args:
            queries: A list of search queries to execute.

        Returns:
            A dictionary containing search results for each query.
        """
        return await query_google(queries, context)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=google_search_tool,
        name="google_search",
        description="Perform a Google search to retrieve information from the web. Useful for finding up-to-date information, facts, or documentation. Provide a list of specific search queries.",
    )

    # Log registration
    if context.services_manager and context.services_manager.logging_service:
        await context.services_manager.logging_service.info(
            "[MCP] Registered Google Search tool: google_search"
        )
