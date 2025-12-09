"""
Discord DM Tool for sending direct messages to users.

This tool allows the bot to send DMs to Discord users by their user ID.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager


async def send_discord_dm(user_id: str, message: str, context: Context) -> dict:
    """
    Send a Discord DM to a user.

    Args:
        user_id: Discord user UUID (snowflake ID as string)
        message: Message content as plaintext (no embeds)
        context: Application context for accessing the bot

    Returns:
        dict with status and details:
            - success (bool): Whether the DM was sent successfully
            - message_id (str): ID of the sent message if successful
            - error (str): Error message if failed
    """
    try:
        # Get the bot instance from context
        if not context or not context.bot:
            return {
                "success": False,
                "error": "Bot instance not available in context",
            }

        bot = context.bot

        # Convert user_id to integer (Discord snowflakes are integers)
        try:
            user_id_int = int(user_id)
        except ValueError:
            return {
                "success": False,
                "error": f"Invalid user ID format: {user_id}. Must be a numeric Discord user ID.",
            }

        # Fetch the user object
        try:
            user = await bot.fetch_user(user_id_int)
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to fetch user with ID {user_id}: {str(e)}",
            }

        # Send the DM
        try:
            dm_message = await user.send(message)

            # Log the successful DM
            if context.services_manager and context.services_manager.logging_service:
                await context.services_manager.logging_service.info(
                    f"[DISCORD_DM_TOOL] Sent DM to user {user.name} ({user_id}): {message[:50]}..."
                )

            return {
                "success": True,
                "message_id": str(dm_message.id),
                "recipient": (
                    f"{user.name}#{user.discriminator}" if user.discriminator != "0" else user.name
                ),
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to send DM to user {user.name}: {str(e)}",
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Unexpected error in send_discord_dm: {str(e)}",
        }


async def register_discord_tools(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register Discord-related tools with the MCP manager.

    Args:
        mcp_manager: The MCP manager instance to register tools with
        context: Application context for tool execution
    """

    # Create a closure that captures the context
    async def send_dm_tool(user_id: str, message: str) -> dict:
        """
        Send a Discord DM to a user.

        Args:
            user_id: Discord user ID (snowflake)
            message: Message content as plaintext

        Returns:
            Result dictionary with success status and details
        """
        return await send_discord_dm(user_id, message, context)

    # Register the tool with MCP manager
    mcp_manager.add_tool_from_function(
        func=send_dm_tool,
        name="send_discord_dm",
        description="Send a direct message to a Discord user by their user ID. The message will be sent as plaintext (no embeds). Use this to notify users, send private information, or communicate outside of public channels.",
    )

    # Log registration
    if context.services_manager and context.services_manager.logging_service:
        await context.services_manager.logging_service.info(
            "[MCP] Registered Discord DM tool: send_discord_dm"
        )
