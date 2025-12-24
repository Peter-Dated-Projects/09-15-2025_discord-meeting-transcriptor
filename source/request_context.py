"""
Request Context Module.

This module provides context variables for storing request-scoped information
such as the current guild ID, thread ID, and user ID. This allows tools and
services to access this information without it being explicitly passed through
every function call.
"""

from contextvars import ContextVar
from typing import Optional

# Context variables for request-scoped data
current_guild_id: ContextVar[Optional[str]] = ContextVar("current_guild_id", default=None)
current_thread_id: ContextVar[Optional[str]] = ContextVar("current_thread_id", default=None)
current_user_id: ContextVar[Optional[str]] = ContextVar("current_user_id", default=None)


def set_request_context(
    guild_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Set the current request context variables.

    Args:
        guild_id: The ID of the current guild
        thread_id: The ID of the current thread
        user_id: The ID of the current user
    """
    if guild_id is not None:
        current_guild_id.set(guild_id)
    if thread_id is not None:
        current_thread_id.set(thread_id)
    if user_id is not None:
        current_user_id.set(user_id)


def clear_request_context() -> None:
    """
    Clear the current request context variables.
    """
    current_guild_id.set(None)
    current_thread_id.set(None)
    current_user_id.set(None)
