"""
Conversation Control Tool for managing bot monitoring behavior.

This tool allows the LLM to stop monitoring a channel/thread, which
prevents the bot from responding to messages until it's mentioned again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from source.request_context import current_thread_id

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager


async def stop_conversation_monitoring(context: Context) -> dict:
    """
    Stop monitoring the current conversation thread.

    The bot will no longer respond to messages in this thread unless
    it is mentioned again. This is useful when the user indicates they
    are done with the conversation or want to end the interaction.

    This tool uses the request context to determine which thread to stop
    monitoring.

    Args:
        context: Application context for accessing services

    Returns:
        dict with status and details:
            - success (bool): Whether monitoring was stopped successfully
            - thread_id (str): The thread ID that was stopped
            - message (str): Status message
            - error (str): Error message if failed
    """
    try:
        # Get the request context to find out which thread we're in
        thread_id = current_thread_id.get()

        if not thread_id:
            return {
                "success": False,
                "error": "Could not determine the current thread. This tool must be called within a conversation thread.",
            }

        # Get the conversation manager from context
        if not context or not context.services_manager:
            return {
                "success": False,
                "error": "Services manager not available in context",
            }

        conversation_manager = context.services_manager.conversation_manager

        if not conversation_manager:
            return {
                "success": False,
                "error": "Conversation manager not available",
            }

        # Get SQL manager for persistence
        conversations_sql_manager = context.services_manager.conversations_sql_manager

        # Stop monitoring this thread
        was_monitoring = conversation_manager.stop_monitoring(thread_id, conversations_sql_manager)

        # Log the action
        if context.services_manager.logging_service:
            await context.services_manager.logging_service.info(
                f"[CONVERSATION_CONTROL] Stopped monitoring thread {thread_id}"
            )

        if was_monitoring:
            return {
                "success": True,
                "thread_id": thread_id,
                "message": "Successfully stopped monitoring this conversation. The bot will no longer respond to messages in this thread unless mentioned again.",
            }
        else:
            return {
                "success": False,
                "thread_id": thread_id,
                "error": "This thread was not being monitored or does not exist.",
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error in stop_conversation_monitoring: {str(e)}",
        }


async def register_conversation_control_tools(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register conversation control tools with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """

    # Create a closure that captures the context
    async def stop_monitoring_tool() -> dict:
        """
        Stop monitoring the current conversation thread.

        Use this tool when the user indicates they are done with the conversation
        or explicitly asks to stop, end, or leave the conversation. The bot will
        no longer respond to messages in this thread unless it is mentioned again.

        Examples of when to use this:
        - User says "goodbye", "that's all", "thanks, I'm done", etc.
        - User asks you to stop responding or leave the conversation
        - Conversation has naturally concluded and user confirms they're done

        Do NOT use this tool:
        - In the middle of an ongoing conversation
        - When the user has follow-up questions
        - Just because the user hasn't said anything for a while

        Returns:
            Result dictionary with success status and details
        """
        return await stop_conversation_monitoring(context)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=stop_monitoring_tool,
        name="stop_conversation_monitoring",
        description="Stop monitoring this conversation thread. The bot will no longer respond to messages in this thread unless mentioned again. Use this when the user indicates they are done with the conversation or explicitly asks to end it. DO NOT use this in the middle of an active conversation or when the user might have follow-up questions.",
    )
