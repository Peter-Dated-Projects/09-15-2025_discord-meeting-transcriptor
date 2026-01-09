"""
Instagram Reel Processing Tool for triggering reel analysis workflow.

This tool allows the LLM to trigger the Instagram reel processing workflow
when it detects a reel URL in the conversation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager

logger = logging.getLogger(__name__)


async def process_instagram_reel(reel_url: str, message_id: str, context: Context) -> dict:
    """
    Trigger the Instagram reel processing workflow.

    This function starts an async task to process a reel (download, transcribe, analyze)
    and returns immediately with a status message.

    Args:
        reel_url: The Instagram reel URL to process
        message_id: The Discord message ID containing the reel
        context: Application context

    Returns:
        Dictionary with status information
    """
    if not context.services_manager:
        return {
            "success": False,
            "error": "Services manager not available",
        }

    # Import here to avoid circular imports
    from discord import Message
    from source.request_context import current_message

    message = current_message.get()
    if not message or not isinstance(message, Message):
        return {
            "success": False,
            "error": "Message context not available",
        }

    guild_id = str(message.guild.id) if message.guild else "DM"

    # Check if already processed
    if context.services_manager.instagram_reels_manager.is_reel_processed(reel_url, guild_id):
        return {
            "success": False,
            "already_processed": True,
            "message": "This reel has already been analyzed and is available in the database.",
        }

    # Mark as processing to prevent duplicates
    context.services_manager.instagram_reels_manager.mark_reel_processed(reel_url, guild_id)

    # Get the reels cog to access the async processing method
    reels_cog = None
    for cog in context.bot.cogs.values():
        if cog.__class__.__name__ == "Reels":
            reels_cog = cog
            break

    if not reels_cog:
        return {
            "success": False,
            "error": "Reels cog not loaded",
        }

    # Launch the async processing task
    try:
        task = asyncio.create_task(reels_cog._process_reel_async(message, reel_url))
        reels_cog._active_tasks.add(task)
        task.add_done_callback(reels_cog._active_tasks.discard)

        await context.services_manager.logging_service.info(
            f"[Reel Process Tool] Launched async workflow for {reel_url}"
        )

        return {
            "success": True,
            "message": "Reel processing started. The analysis will be posted as a reply when complete.",
            "reel_url": reel_url,
        }

    except Exception as e:
        await context.services_manager.logging_service.error(
            f"[Reel Process Tool] Failed to launch workflow: {e}", exc_info=True
        )
        return {
            "success": False,
            "error": str(e),
        }


def register_reel_process_tool(mcp_manager: MCPManager, context: Context):
    """
    Register the Instagram reel processing tool with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance
        context: Application context
    """

    @mcp_manager.tool(
        name="process_instagram_reel",
        description=(
            "Process an Instagram reel URL by downloading, transcribing, and analyzing it. "
            "This tool should be used when the user shares an Instagram reel URL and expects analysis. "
            "The tool will start an async workflow and return immediately. The analysis result will be "
            "posted as a reply to the original message when complete. "
            "Use this tool ONLY when you detect an Instagram reel URL in the conversation."
        ),
    )
    async def process_reel_tool(reel_url: str) -> str:
        """
        Process an Instagram reel and generate a summary.

        Args:
            reel_url: The Instagram reel URL (must be instagram.com/reel/... or instagram.com/p/...)

        Returns:
            JSON string with processing status
        """
        from source.request_context import current_message

        message = current_message.get()
        if not message:
            return '{"success": false, "error": "Message context not available"}'

        message_id = str(message.id)

        result = await process_instagram_reel(reel_url, message_id, context)

        import json

        return json.dumps(result, indent=2)

    logger.info("Registered process_instagram_reel tool")
