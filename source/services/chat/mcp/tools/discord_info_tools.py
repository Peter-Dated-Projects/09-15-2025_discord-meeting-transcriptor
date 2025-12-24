"""
Discord Info Tools for retrieving information about users, guilds, and threads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List

import discord

from source.request_context import current_guild_id, current_thread_id

if TYPE_CHECKING:
    from source.context import Context
    from source.services.chat.mcp import MCPManager


async def get_usernames_from_ids(user_ids: List[str], context: Context) -> Dict[str, str]:
    """
    Get usernames for a list of Discord user IDs.

    Args:
        user_ids: List of Discord user IDs (strings)
        context: Application context

    Returns:
        Dictionary mapping user_id to server username (display name) or global name.
    """
    if not context or not context.bot:
        return {"error": "Bot instance not available"}

    bot = context.bot
    results = {}

    for user_id in user_ids:
        try:
            uid = int(user_id)
            user = bot.get_user(uid)
            if not user:
                try:
                    user = await bot.fetch_user(uid)
                except discord.NotFound:
                    results[user_id] = "Unknown User"
                    continue
                except Exception:
                    results[user_id] = "Error Fetching User"
                    continue

            results[user_id] = user.display_name
        except ValueError:
            results[user_id] = "Invalid ID"

    return results


async def get_guild_name(guild_id: str, context: Context) -> str:
    """
    Get the name of a guild by its ID.

    Args:
        guild_id: Discord guild ID
        context: Application context

    Returns:
        The name of the guild.
    """
    if not context or not context.bot:
        return "Error: Bot instance not available"

    bot = context.bot
    try:
        gid = int(guild_id)
        guild = bot.get_guild(gid)
        if not guild:
            try:
                guild = await bot.fetch_guild(gid)
            except discord.NotFound:
                return "Guild Not Found"
            except discord.Forbidden:
                return "Guild Access Forbidden"

        return guild.name
    except ValueError:
        return "Invalid Guild ID"
    except Exception as e:
        return f"Error: {str(e)}"


async def get_thread_members(thread_id: str, context: Context) -> List[str]:
    """
    Get the users in a thread.

    Args:
        thread_id: Discord thread ID
        context: Application context

    Returns:
        List of usernames in the thread.
    """
    if not context or not context.bot:
        return ["Error: Bot instance not available"]

    bot = context.bot
    try:
        tid = int(thread_id)
        # Threads are channels in discord.py
        thread = bot.get_channel(tid)

        if not thread:
            try:
                thread = await bot.fetch_channel(tid)
            except discord.NotFound:
                return ["Thread Not Found"]
            except discord.Forbidden:
                return ["Thread Access Forbidden"]

        if not isinstance(thread, discord.Thread):
            return ["Channel is not a thread"]

        members = await thread.fetch_members()
        # fetch_members returns ThreadMember objects, which have an id.
        # We need to resolve these to users to get names.

        usernames = []
        for member in members:
            # ThreadMember might have a member attribute if cached, or we fetch user
            user = bot.get_user(member.id)
            if not user:
                try:
                    user = await bot.fetch_user(member.id)
                except:
                    usernames.append(f"Unknown User ({member.id})")
                    continue
            usernames.append(user.display_name)

        return usernames

    except ValueError:
        return ["Invalid Thread ID"]
    except Exception as e:
        return [f"Error: {str(e)}"]


async def get_guild_members(guild_id: str, context: Context) -> Dict[str, Any]:
    """
    Get all users and their usernames in a guild.

    Args:
        guild_id: Discord guild ID
        context: Application context

    Returns:
        Dictionary of user_id: {username: str, status: str, roles: List[Dict]} for all members.
    """
    if not context or not context.bot:
        return {"error": "Bot instance not available"}

    bot = context.bot
    try:
        gid = int(guild_id)
        guild = bot.get_guild(gid)
        if not guild:
            try:
                guild = await bot.fetch_guild(gid)
            except:
                return {"error": "Guild Not Found or Inaccessible"}

        # We need to ensure members are chunked/cached if intents are enabled
        if not guild.chunked:
            await guild.chunk()

        return {
            str(member.id): {
                "name": member.display_name,
                "status": str(member.status),
                "roles": [{"id": str(role.id), "name": role.name} for role in member.roles],
            }
            for member in guild.members
        }

    except ValueError:
        return {"error": "Invalid Guild ID"}
    except Exception as e:
        return {"error": f"Error: {str(e)}"}


async def get_current_guild_id(context: Context) -> str:
    """
    Get the guild ID of the current context.

    Args:
        context: Application context

    Returns:
        Guild ID as string, or error message.
    """
    if not context or not context.bot:
        return "Error: Bot instance not available"

    guild_id = current_guild_id.get()
    if not guild_id:
        return "Error: No current guild context available"

    return guild_id


async def get_current_thread_id(context: Context) -> str:
    """
    Get the thread ID of the current context.

    Args:
        context: Application context

    Returns:
        Thread ID as string, or error message.
    """
    if not context or not context.bot:
        return "Error: Bot instance not available"

    thread_id = current_thread_id.get()
    if not thread_id:
        return "Error: No current thread context available"

    return thread_id


async def get_guild_roles(context: Context) -> List[Dict[str, Any]]:
    """
    Get all roles in the current guild.

    Args:
        context: Application context

    Returns:
        List of dictionaries containing role id, name, and position.
    """
    if not context or not context.bot:
        return [{"error": "Bot instance not available"}]

    guild_id = current_guild_id.get()
    if not guild_id:
        return [{"error": "No current guild context available"}]

    try:
        gid = int(guild_id)
        guild = context.bot.get_guild(gid)
        if not guild:
            try:
                guild = await context.bot.fetch_guild(gid)
            except Exception as e:
                return [{"error": f"Failed to fetch guild: {str(e)}"}]

        roles = []
        for role in guild.roles:
            roles.append(
                {"id": str(role.id), "name": role.name, "position": role.position}
            )

        # Sort by position (descending)
        roles.sort(key=lambda x: x["position"], reverse=True)

        return roles

    except ValueError:
        return [{"error": "Invalid Guild ID format"}]
    except Exception as e:
        return [{"error": f"Unexpected error: {str(e)}"}]


async def get_users_with_role(role_id: str, context: Context) -> List[Dict[str, str]]:
    """
    Get all users with a specific role in the current guild.

    Args:
        role_id: The ID of the role
        context: Application context

    Returns:
        List of dictionaries containing user id, name, and display_name.
    """
    if not context or not context.bot:
        return [{"error": "Bot instance not available"}]

    guild_id = current_guild_id.get()
    if not guild_id:
        return [{"error": "No current guild context available"}]

    try:
        gid = int(guild_id)
        guild = context.bot.get_guild(gid)
        if not guild:
            try:
                guild = await context.bot.fetch_guild(gid)
            except Exception as e:
                return [{"error": f"Failed to fetch guild: {str(e)}"}]

        try:
            rid = int(role_id)
        except ValueError:
            return [{"error": "Invalid Role ID format"}]

        role = guild.get_role(rid)
        if not role:
            try:
                roles = await guild.fetch_roles()
                role = discord.utils.get(roles, id=rid)
            except Exception as e:
                return [{"error": f"Failed to fetch roles: {str(e)}"}]

        if not role:
            return [{"error": "Role not found in guild"}]

        users = []
        for member in role.members:
            users.append(
                {
                    "id": str(member.id),
                    "name": member.name,
                    "display_name": member.display_name,
                }
            )

        return users

    except Exception as e:
        return [{"error": f"Unexpected error: {str(e)}"}]


async def register_discord_info_tools(mcp_manager: MCPManager, context: Context) -> None:
    """
    Register Discord info tools with the MCP manager.
    """

    async def get_usernames_tool(user_ids: List[str]) -> Dict[str, str]:
        return await get_usernames_from_ids(user_ids, context)

    async def get_guild_name_tool(guild_id: str) -> str:
        return await get_guild_name(guild_id, context)

    async def get_thread_members_tool(thread_id: str) -> List[str]:
        return await get_thread_members(thread_id, context)

    async def get_guild_members_tool(guild_id: str) -> Dict[str, Any]:
        return await get_guild_members(guild_id, context)

    async def get_current_guild_id_tool() -> str:
        return await get_current_guild_id(context)

    async def get_current_thread_id_tool() -> str:
        return await get_current_thread_id(context)

    async def get_guild_roles_tool() -> List[Dict[str, Any]]:
        return await get_guild_roles(context)

    async def get_users_with_role_tool(role_id: str) -> List[Dict[str, str]]:
        return await get_users_with_role(role_id, context)

    mcp_manager.add_tool_from_function(
        get_usernames_tool,
        name="get_usernames_from_ids",
        description="Get usernames for a list of Discord user IDs.",
    )

    mcp_manager.add_tool_from_function(
        get_guild_name_tool, name="get_guild_name", description="Get the name of a guild by its ID."
    )

    mcp_manager.add_tool_from_function(
        get_thread_members_tool,
        name="get_thread_members",
        description="Get the usernames of members in a Discord thread.",
    )

    mcp_manager.add_tool_from_function(
        get_guild_members_tool,
        name="get_guild_members",
        description="Get all users and their usernames in a guild.",
    )

    mcp_manager.add_tool_from_function(
        get_current_guild_id_tool,
        name="get_current_guild_id",
        description="Get the guild ID of the current context (if applicable).",
    )

    mcp_manager.add_tool_from_function(
        get_current_thread_id_tool,
        name="get_current_thread_id",
        description="Get the thread ID of the current context (if applicable).",
    )

    mcp_manager.add_tool_from_function(
        get_guild_roles_tool,
        name="get_guild_roles",
        description="Get all roles in the current guild, including their IDs, names, and positions.",
    )

    mcp_manager.add_tool_from_function(
        get_users_with_role_tool,
        name="get_users_with_role",
        description="Get all users who have a specific role in the current guild.",
    )
