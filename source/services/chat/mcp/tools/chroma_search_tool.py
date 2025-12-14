"""
ChromaDB Search Tool for querying meeting summaries.

This tool allows the bot to search the vector database for relevant meeting summaries.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Dict, Any

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager

from source.services.transcription.text_embedding_manager.manager import EmbeddingModelHandler


async def query_chroma_summaries(
    query: str | List[str], context: Context, n_results: int = 5
) -> dict:
    """
    Search the ChromaDB summaries collection for relevant meetings.

    Args:
        query: The search query string or list of strings
        context: Application context
        n_results: Number of results to return per query

    Returns:
        dict with search results or error message
    """
    if not context.services_manager:
        return {"error": "Services manager not available"}

    if not context.services_manager.server:
        return {"error": "Server manager not available"}

    gpu_manager = context.services_manager.gpu_resource_manager
    vector_db_client = context.services_manager.server.vector_db_client
    logging_service = context.services_manager.logging_service

    try:
        # 1. Generate Embedding
        queries = [query] if isinstance(query, str) else query
        embeddings = []

        # Acquire GPU lock for embedding generation
        # We use a generic job_id since this is a synchronous tool call
        async with gpu_manager.acquire_lock(
            job_type="chatbot",
            job_id="tool_call",
            metadata={"query_count": len(queries)},
        ):
            handler = EmbeddingModelHandler()
            try:
                await asyncio.to_thread(handler.load_model)

                # Embed the queries
                # Note: We removed the instruction prefix to match admin_page.py behavior
                embeddings = await asyncio.to_thread(
                    lambda: handler.encode(queries, batch_size=len(queries))
                )

            finally:
                await asyncio.to_thread(handler.offload_model)

        # 2. Query ChromaDB
        collection_name = "summaries"

        # Get collection (ChromaDB operations are synchronous)
        collection = await asyncio.to_thread(
            lambda: vector_db_client.get_or_create_collection(collection_name)
        )

        # Query the collection
        results = await asyncio.to_thread(
            lambda: collection.query(
                query_embeddings=embeddings,
                n_results=n_results,
                include=["metadatas", "documents", "distances"],
            )
        )

        # 3. Format Results
        formatted_results = []

        if results and results["ids"]:
            # results["ids"] is a list of lists (one list per query)
            for q_idx in range(len(results["ids"])):
                ids = results["ids"][q_idx]
                metadatas = results["metadatas"][q_idx]
                documents = results["documents"][q_idx]
                distances = results["distances"][q_idx]

                for i in range(len(ids)):
                    formatted_results.append(
                        {
                            "meeting_id": metadatas[i].get("meeting_id"),
                            "summary_text": documents[i],
                            "distance": distances[i],
                            "metadata": metadatas[i],
                            "query": queries[q_idx],
                        }
                    )

        return {"results": formatted_results}

    except Exception as e:
        await logging_service.error(f"Error in chroma_search_tool: {e}")
        print(f"Error in chroma_search_tool: {e}")
        return {"error": str(e)}
