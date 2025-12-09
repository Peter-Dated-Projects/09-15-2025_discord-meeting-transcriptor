"""
Google Query Tool for using Google Custom Search API.

This tool allows the bot to perform Google searches and retrieve relevant information.
"""

from __future__ import annotations

import os
import asyncio
import time
import requests
from bs4 import BeautifulSoup
from typing import TYPE_CHECKING, List, Dict, Any
from googleapiclient.discovery import build

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager


# --- Web Page Caching ---

_WEBPAGE_CACHE: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 300  # 5 minutes
WORDS_PER_PAGE = 500


def _clean_cache() -> None:
    """Remove expired entries from the cache."""
    current_time = time.time()
    expired_keys = [
        k for k, v in _WEBPAGE_CACHE.items() if current_time - v["timestamp"] > CACHE_TTL
    ]
    for k in expired_keys:
        del _WEBPAGE_CACHE[k]


def _fetch_and_parse(url: str) -> List[str]:
    """
    Fetch a webpage, parse it, and split it into pages of text.
    """
    try:
        # Use a real user agent to avoid being blocked
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script and style elements
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.decompose()

        text = soup.get_text()

        # Clean up text
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = "\n".join(chunk for chunk in chunks if chunk)

        words = text.split()
        pages = []

        if not words:
            return ["No readable text content found on this page."]

        for i in range(0, len(words), WORDS_PER_PAGE):
            pages.append(" ".join(words[i : i + WORDS_PER_PAGE]))

        return pages
    except Exception as e:
        return [f"Error fetching page: {str(e)}"]


async def read_webpage(url: str, page: int = 1) -> dict:
    """
    Read content from a webpage with pagination.

    Args:
        url: The URL to read
        page: The page number to retrieve (1-based)

    Returns:
        dict with content and pagination info
    """
    _clean_cache()
    current_time = time.time()

    # Check cache
    cached_data = _WEBPAGE_CACHE.get(url)
    if cached_data and (current_time - cached_data["timestamp"] < CACHE_TTL):
        pages = cached_data["pages"]
    else:
        # Fetch in thread to avoid blocking
        pages = await asyncio.to_thread(_fetch_and_parse, url)
        _WEBPAGE_CACHE[url] = {"pages": pages, "timestamp": current_time}

    # Adjust page to 0-indexed
    page_idx = page - 1
    if page_idx < 0:
        page_idx = 0

    if page_idx >= len(pages):
        return {
            "error": f"Page {page} out of range. Total pages: {len(pages)}",
            "total_pages": len(pages),
            "current_page": page,
            "url": url,
        }

    return {
        "url": url,
        "content": pages[page_idx],
        "current_page": page,
        "total_pages": len(pages),
        "words_on_page": len(pages[page_idx].split()),
    }


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

    # Initialize service once to avoid rebuilding it for every query
    service = build("customsearch", "v1", developerKey=api_key, cache_discovery=False)

    def _search(query):
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
        description="Perform a Google search to retrieve information from the web. Returns titles, links, and snippets. It's suggested to use 'read_webpage' to read the full content of a link.",
    )

    # Register the read_webpage tool
    mcp_manager.add_tool_from_function(
        func=read_webpage,
        name="read_webpage",
        description="Read the content of a webpage. Returns text content in sections of ~500 words (if you need more info, read more sections). Provide the URL and optionally a section number (default 1). ",
    )

    # Log registration
    if context.services_manager and context.services_manager.logging_service:
        await context.services_manager.logging_service.info(
            "[MCP] Registered Google Search tools: google_search, read_webpage"
        )
