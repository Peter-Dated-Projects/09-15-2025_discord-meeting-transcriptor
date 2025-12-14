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


async def run_meeting_search_subroutine(query: str, context: Context) -> Any:
    """
    Run the meeting search subroutine to find and summarize meetings.
    """
    if not context.services_manager:
        return "Error: Services manager not available"

    # Import here to avoid circular dependency
    from source.services.chat.mcp.subroutine_manager.subroutines.meeting_search import (
        create_meeting_search_subroutine,
    )
    from langchain_core.messages import HumanMessage
    import os

    ollama_manager = context.services_manager.ollama_request_manager
    model = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:12b")

    # Create subroutine
    subroutine = create_meeting_search_subroutine(
        ollama_request_manager=ollama_manager, context=context, model=model
    )

    # Run subroutine
    try:
        # The input state expects "messages"
        initial_state = {"messages": [HumanMessage(content=query)]}
        # Use ainvoke to run the graph
        result = await subroutine.ainvoke(initial_state)

        print(result)

        # The result is a list of messages. The last message should be the synthesis.
        if result and "messages" in result and len(result["messages"]) > 0:
            # Return the full list of messages to preserve the conversation context
            # including internal tool calls and thoughts
            messages = result["messages"]
            serialized_messages = []
            for m in messages:
                if hasattr(m, "model_dump"):
                    serialized_messages.append(m.model_dump())
                elif hasattr(m, "dict"):
                    serialized_messages.append(m.dict())
                else:
                    serialized_messages.append({"type": m.type, "content": m.content})
            return serialized_messages
        return "No results found."
    except Exception as e:
        if context.services_manager.logging_service:
            await context.services_manager.logging_service.error(
                f"Error running meeting search subroutine: {e}"
            )
        return f"Error: {str(e)}"


async def register_chroma_tools(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register ChromaDB Search tools with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """

    # Create a closure that captures the context
    async def search_meetings_tool(query: str) -> str:
        """
        Search for past meetings based on a query.
        Returns meeting IDs and relevant summary snippets.

        Args:
            query: The search query (e.g., "budget discussion", "project alpha launch").
        """
        return await run_meeting_search_subroutine(query, context)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=search_meetings_tool,
        name="search_meetings",
        description="Search the database of past meeting summaries for relevant discussions. Returns meeting IDs and summary snippets.",
    )

    # Log registration
    if context.services_manager and context.services_manager.logging_service:
        await context.services_manager.logging_service.info(
            "[MCP] Registered ChromaDB Search tools: search_meetings"
        )
