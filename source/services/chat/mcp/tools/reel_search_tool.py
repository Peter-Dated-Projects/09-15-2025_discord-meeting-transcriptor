"""
Instagram Reel Search Tool for querying reel summaries in ChromaDB.

This tool allows the bot to search the vector database for relevant Instagram reels
that have been posted in the guild. It includes query refinement using ministral-3:3b
for better semantic search results.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Dict, List

from source.request_context import current_guild_id

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager

from source.services.transcription.text_embedding_manager.manager import EmbeddingModelHandler


async def refine_search_query(raw_query: str, context: Context) -> str:
    """
    Refine and clean up a search query using ministral-3:3b.

    This function corrects semantic errors, removes noise, and optimizes
    the query for semantic search in the vector database.

    Args:
        raw_query: The raw search query from the user
        context: Application context

    Returns:
        Refined search query optimized for semantic search
    """
    if not context.services_manager:
        return raw_query

    ollama_manager = context.services_manager.ollama_request_manager
    logging_service = context.services_manager.logging_service

    system_prompt = """You are a search query optimizer. Your task is to take a user's raw search query and refine it for semantic search.

Rules:
1. Fix any spelling or grammatical errors
2. Remove unnecessary words that don't add semantic value
3. Expand abbreviations if they're ambiguous
4. Keep the core intent and meaning
5. Make it concise but descriptive
6. Output ONLY the refined query, nothing else

Examples:
Input: "show me reelz about cookin stuff"
Output: "cooking recipes and food preparation"

Input: "wat reels did we post abt travel last week"
Output: "travel destinations and vacation experiences"

Input: "reels with funny cats"
Output: "funny cat videos and humorous feline content"

Output ONLY the refined query, no explanations."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Refine this search query: {raw_query}"},
    ]

    try:
        # Use ministral-3:3b for fast query refinement
        response = await ollama_manager.query(
            model="ministral-3:3b",
            messages=messages,
            temperature=0.3,  # Low temperature for consistent refinement
            num_predict=100,  # Queries should be short
        )

        refined_query = response.content.strip()

        await logging_service.info(
            f"[Reel Search] Query refined: '{raw_query}' -> '{refined_query}'"
        )

        return refined_query

    except Exception as e:
        await logging_service.error(f"[Reel Search] Query refinement failed: {e}")
        # Fall back to original query
        return raw_query


async def query_reel_summaries(
    query: str, context: Context, n_results: int = 20, refine_query: bool = True
) -> dict:
    """
    Search the ChromaDB reels collection for relevant Instagram reels.

    This function:
    1. Optionally refines the query using ministral-3:3b
    2. Gets the current guild ID from context
    3. Generates embeddings for the query
    4. Searches the guild's reel collection
    5. Deduplicates results by unique reel URL
    6. Returns up to n_results unique reels

    Args:
        query: The search query string
        context: Application context
        n_results: Maximum number of unique reel results to return (default: 20)
        refine_query: Whether to refine the query with LLM (default: True)

    Returns:
        dict with search results or error message

    Example Result:
        {
            "results": [
                {
                    "reel_url": "https://instagram.com/reel/xyz",
                    "summary": "A reel about cooking pasta...",
                    "distance": 0.23,
                    "metadata": {
                        "message_id": "123",
                        "user_id": "456",
                        "channel_id": "789",
                        "timestamp": "2026-01-08T12:00:00"
                    }
                },
                ...
            ],
            "query_original": "show me cooking reels",
            "query_refined": "cooking recipes and food preparation",
            "total_results": 15,
            "unique_reels": 15
        }
    """
    if not context.services_manager:
        return {"error": "Services manager not available"}

    if not context.services_manager.server:
        return {"error": "Server manager not available"}

    services = context.services_manager
    gpu_manager = services.gpu_resource_manager
    vector_db_client = services.server.vector_db_client
    logging_service = services.logging_service

    # Get current guild ID from request context
    guild_id = current_guild_id.get()

    if not guild_id:
        return {
            "error": "Could not determine guild ID from context. Reel search is only available in guild channels."
        }

    try:
        # Step 1: Refine the query if requested
        original_query = query
        if refine_query:
            query = await refine_search_query(query, context)

        await logging_service.info(f"[Reel Search] Searching guild {guild_id} for: {query}")

        # Step 2: Generate Embedding
        embeddings = []

        async with gpu_manager.acquire_lock(
            job_type="chatbot",
            job_id="reel_search_tool",
            metadata={"query": query},
        ):
            handler = EmbeddingModelHandler()
            try:
                await asyncio.to_thread(handler.load_model)

                embeddings = await asyncio.to_thread(lambda: handler.encode([query], batch_size=1))

            finally:
                await asyncio.to_thread(handler.offload_model)

        # Step 3: Query ChromaDB
        collection_name = f"reels_{guild_id}"

        # Check if collection exists
        collection_exists = await asyncio.to_thread(
            lambda: vector_db_client.collection_exists(collection_name)
        )

        if not collection_exists:
            return {
                "error": f"No reels have been stored for this guild yet. Post some Instagram reels in a monitored channel first!",
                "query_original": original_query,
                "query_refined": query if refine_query else None,
            }

        # Get collection
        collection = await asyncio.to_thread(
            lambda: vector_db_client.get_or_create_collection(collection_name)
        )

        # Query with guild_id filter (we search more than needed for deduplication)
        # Request 2x n_results to ensure we have enough after deduplication
        results = await asyncio.to_thread(
            lambda: collection.query(
                query_embeddings=embeddings,
                n_results=min(n_results * 2, 100),  # Cap at 100 raw results
                where={"guild_id": guild_id},
                include=["metadatas", "documents", "distances"],
            )
        )

        # Step 4: Format and Deduplicate Results
        seen_urls = set()
        formatted_results = []

        if results and results["ids"]:
            ids = results["ids"][0]  # First query results
            metadatas = results["metadatas"][0]
            documents = results["documents"][0]
            distances = results["distances"][0]

            for i in range(len(ids)):
                metadata = metadatas[i]
                reel_url = metadata.get("reel_url", "")

                # Skip if we've already seen this reel URL
                if reel_url in seen_urls:
                    continue

                seen_urls.add(reel_url)

                formatted_results.append(
                    {
                        "reel_url": reel_url,
                        "summary": documents[i],
                        "distance": distances[i],
                        "metadata": {
                            "message_id": metadata.get("message_id"),
                            "message_content": metadata.get("message_content"),
                            "user_id": metadata.get("user_id"),
                            "channel_id": metadata.get("channel_id"),
                            "timestamp": metadata.get("timestamp"),
                        },
                    }
                )

                # Stop once we have enough unique results
                if len(formatted_results) >= n_results:
                    break

        await logging_service.info(
            f"[Reel Search] Found {len(formatted_results)} unique reel(s) for query: {query}"
        )

        return {
            "results": formatted_results,
            "query_original": original_query,
            "query_refined": query if refine_query else None,
            "total_results": len(results["ids"][0]) if results and results["ids"] else 0,
            "unique_reels": len(formatted_results),
        }

    except Exception as e:
        await logging_service.error(f"[Reel Search] Error: {e}")
        return {
            "error": str(e),
            "query_original": original_query,
            "query_refined": query if refine_query else None,
        }


async def register_reel_search_tool(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register the Instagram Reel Search tool with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """

    # Create a closure that captures the context
    async def search_reels_tool(query: str) -> Any:
        """
        Search for Instagram reels in the current guild's vector database.

        This tool automatically refines your query for better semantic search,
        filters by the current guild, and returns up to 20 unique reels.

        Args:
            query: What you're looking for in the reels (e.g., "cooking recipes",
                   "travel destinations", "funny cats")

        Returns:
            Dictionary containing:
            - results: List of matching reels with summaries and metadata
            - query_original: Your original query
            - query_refined: The optimized query used for search
            - unique_reels: Number of unique reels found
        """
        return await query_reel_summaries(query, context, n_results=20, refine_query=True)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=search_reels_tool,
        name="search_instagram_reels",
        description="Search Instagram reels posted in this guild. Automatically refines the query and returns up to 20 unique reels with their summaries. Only works in channels where reel monitoring is enabled.",
    )

    # Log registration
    if context.services_manager and context.services_manager.logging_service:
        await context.services_manager.logging_service.info(
            "[MCP] Registered Instagram Reel Search tool: search_instagram_reels"
        )
