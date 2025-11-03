import uuid
from zoneinfo import ZoneInfo
import discord
from datetime import datetime
import hashlib

# -------------------------------------------------------------- #
# Constants
# -------------------------------------------------------------- #


# unique role description for bot
BOT_UNIQUE_ROLE_NAME = "Echo"
BOT_UNIQUE_ROLE_COLOR = discord.Color.purple()

DISCORD_USER_ID_MIN_LENGTH = 16  # ranges from 16 -> 20 as time goes on
DISCORD_GUILD_ID_MIN_LENGTH = 17  # ranges from 17 -> 20 as time goes on

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


# -------------------------------------------------------------- #
# Util Functions
# -------------------------------------------------------------- #


def get_current_timestamp_est() -> datetime.datetime:
    """Get the current EST timestamp."""
    return datetime.now(ZoneInfo("EST"))


def calculate_file_sha256(file_path: str) -> str:
    """Calculate the SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()
