"""
ChromaDB Search Tool for querying meeting summaries.

This tool allows the bot to search the vector database for relevant meeting summaries.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, List, Dict, Any

from sqlalchemy import select

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager

from source.server.sql_models import MeetingModel
from source.services.transcription.text_embedding_manager.manager import EmbeddingModelHandler


# Cache for Discord usernames: {user_id: username}
USERNAME_CACHE: Dict[str, str] = {}
# Cache for Discord guilds: {guild_id: guild_name}
GUILD_CACHE: Dict[str, str] = {}


async def _get_username(user_id: str | int, context: Context) -> str:
    """Helper to get username from Discord ID with caching."""
    str_id = str(user_id)
    if str_id in USERNAME_CACHE:
        return USERNAME_CACHE[str_id]

    if not context.bot:
        return "Unknown User"

    try:
        # Try to get from cache first
        user = context.bot.get_user(int(user_id))
        if not user:
            # Fetch from API
            user = await context.bot.fetch_user(int(user_id))

        if user:
            username = user.name
            USERNAME_CACHE[str_id] = username
            return username
    except Exception:
        pass

    return "Unknown User"


async def get_guild_name(guild_id: str | int, context: Context) -> str:
    """Helper to get guild name from Discord ID with caching."""
    str_id = str(guild_id)
    if str_id in GUILD_CACHE:
        return GUILD_CACHE[str_id]

    if not context.bot:
        return "Unknown Guild"

    try:
        # Try to get from cache first
        guild = context.bot.get_guild(int(guild_id))
        if not guild:
            # Fetch from API
            guild = await context.bot.fetch_guild(int(guild_id))

        if guild:
            guild_name = guild.name
            GUILD_CACHE[str_id] = guild_name
            return guild_name
    except Exception:
        pass

    return "Unknown Guild"


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


async def query_chroma_transcriptions(
    meeting_id: str, query: str | List[str], context: Context, n_results: int = 5
) -> dict:
    """
    Search the ChromaDB transcriptions collection for relevant segments within a specific meeting.

    Args:
        meeting_id: The ID of the meeting to search within
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
    sql_client = context.services_manager.server.sql_client
    logging_service = context.services_manager.logging_service

    try:
        # 1. Get Guild ID for the meeting
        stmt = select(MeetingModel).where(MeetingModel.id == meeting_id)
        results = await sql_client.execute(stmt)

        if not results:
            return {"error": f"Meeting with ID {meeting_id} not found."}

        # results is a list of dicts (from row objects)
        meeting = results[0]
        guild_id = meeting.get("guild_id")

        if not guild_id:
            return {"error": f"Guild ID not found for meeting {meeting_id}."}

        # 2. Generate Embedding
        queries = [query] if isinstance(query, str) else query
        embeddings = []

        async with gpu_manager.acquire_lock(
            job_type="chatbot",
            job_id="tool_call",
            metadata={"query_count": len(queries)},
        ):
            handler = EmbeddingModelHandler()
            try:
                await asyncio.to_thread(handler.load_model)
                embeddings = await asyncio.to_thread(
                    lambda: handler.encode(queries, batch_size=len(queries))
                )
            finally:
                await asyncio.to_thread(handler.offload_model)

        # 3. Query ChromaDB
        collection_name = f"embeddings_{guild_id}"

        collection = await asyncio.to_thread(
            lambda: vector_db_client.get_or_create_collection(collection_name)
        )

        # Query with meeting_id filter
        results = await asyncio.to_thread(
            lambda: collection.query(
                query_embeddings=embeddings,
                n_results=n_results,
                where={"meeting_id": meeting_id},
                include=["metadatas", "documents", "distances"],
            )
        )

        # 4. Format Results
        formatted_results = []

        if results and results["ids"]:
            for q_idx in range(len(results["ids"])):
                ids = results["ids"][q_idx]
                metadatas = results["metadatas"][q_idx]
                documents = results["documents"][q_idx]
                distances = results["distances"][q_idx]

                for i in range(len(ids)):
                    # Skip if no document found (shouldn't happen with ids present)
                    if not ids[i]:
                        continue

                    # Process metadata for original content and speaker
                    metadata = metadatas[i]
                    original_content = metadata.get("original_content", documents[i])
                    speaker_id = metadata.get("user_id")

                    formatted_text = original_content
                    if speaker_id:
                        username = await _get_username(speaker_id, context)
                        formatted_text = f"[{username}] <{speaker_id}>: {original_content}"

                    formatted_results.append(
                        {
                            "segment_id": ids[i],
                            "text": formatted_text,
                            "distance": distances[i],
                            "metadata": metadatas[i],
                            "query": queries[q_idx],
                            "guild_id": guild_id,
                        }
                    )

        return {"results": formatted_results}

    except Exception as e:
        await logging_service.error(f"Error in query_chroma_transcriptions: {e}")
        return {"error": str(e)}
