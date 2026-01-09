"""
Conversation Control Tool for managing bot monitoring behavior.

This tool allows the LLM to stop monitoring a channel/thread, which
prevents the bot from responding to messages until it's mentioned again.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from source.request_context import current_thread_id

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager

# Get the context cleaner model from environment
OLLAMA_CONTEXT_CLEANER_MODEL = os.getenv("OLLAMA_CONTEXT_CLEANER_MODEL", "gemma3:12b")


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
            # Run context cleaning workflow to remove goodbye/farewell messages
            try:
                conversation = conversation_manager.get_conversation(thread_id)
                if conversation:
                    # Import here to avoid circular imports
                    from source.services.chat.mcp.subroutine_manager.subroutines.context_cleaning import (
                        ContextCleaningSubroutine,
                    )

                    if context.services_manager.logging_service:
                        await context.services_manager.logging_service.info(
                            f"[CONVERSATION_CONTROL] Running context cleaning for thread {thread_id} after stopping monitoring"
                        )

                    # Create and run the context cleaning subroutine
                    subroutine = ContextCleaningSubroutine(
                        ollama_request_manager=context.services_manager.ollama_request_manager,
                        conversation=conversation,
                        model=OLLAMA_CONTEXT_CLEANER_MODEL,
                        logging_service=context.services_manager.logging_service,
                    )

                    await subroutine.ainvoke({"messages": []})

                    # Save the updated conversation
                    await conversation.save_conversation()

                    if context.services_manager.logging_service:
                        await context.services_manager.logging_service.info(
                            f"[CONVERSATION_CONTROL] Context cleaning completed for thread {thread_id}"
                        )
            except Exception as e:
                # Log the error but don't fail the stop monitoring operation
                if context.services_manager.logging_service:
                    await context.services_manager.logging_service.error(
                        f"[CONVERSATION_CONTROL] Failed to run context cleaning: {str(e)}"
                    )

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

        ⚠️ IMPORTANT: You should actively look for opportunities to use this tool!

        USE THIS TOOL LIBERALLY when:
        - User says "thank you" or "thanks" after getting help (ALWAYS CALL THIS)
        - User says their task/work is done: "job is done", "task completed", "work is finished"
        - User indicates completion: "that's all", "that's everything", "we're done"
        - User says goodbye: "bye", "goodbye", "see you", "later"
        - User dismisses you: "you can go", "thanks I'm done", "no longer needed"
        - Conversation naturally ends after helping with their request
        - User confirms they don't need anything else

        When you see these signals, IMMEDIATELY:
        1. Give a brief, friendly farewell (1-2 sentences max)
        2. Call this tool WITHOUT asking for confirmation

        ONLY ask for confirmation if:
        - User's message is ambiguous or unclear
        - Middle of multi-step task with more steps remaining
        - User explicitly says they'll "be back" or "need more help later"

        After calling this tool, the system will automatically add a monitoring flag.

        Returns:
            Result dictionary with success status and details
        """
        return await stop_conversation_monitoring(context)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=stop_monitoring_tool,
        name="stop_conversation_monitoring",
        description="Stop monitoring when user says 'thanks', 'done', 'goodbye', or indicates completion. USE LIBERALLY - don't ask for confirmation in obvious cases. Call this after helping user with their request and they thank you or signal they're finished.",
    )
