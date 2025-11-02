import uuid

import discord

# -------------------------------------------------------------- #
# Constants
# -------------------------------------------------------------- #


# unique role description for bot
BOT_UNIQUE_ROLE_NAME = "Echo"
BOT_UNIQUE_ROLE_COLOR = discord.Color.purple()


# -------------------------------------------------------------- #
# Generators
# -------------------------------------------------------------- #


def generate_variable_char_uuid(length: int) -> str:
    """Generate a unique identifier of specified length."""
    if length <= 0 or length > 32:
        raise ValueError("Length must be between 1 and 32")
    return uuid.uuid4().hex[:length]


def generate_16_char_uuid() -> str:
    """Generate a unique 16-character identifier."""
    return generate_variable_char_uuid(16)
