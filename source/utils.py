import os

import platform
import uuid
from zoneinfo import ZoneInfo
import discord
from datetime import datetime
import hashlib
import subprocess

# -------------------------------------------------------------- #
# Constants
# -------------------------------------------------------------- #


# unique role description for bot
BOT_UNIQUE_ROLE_NAME = "Echo"
BOT_UNIQUE_ROLE_COLOR = discord.Color.purple()

DISCORD_USER_ID_MIN_LENGTH = 16  # ranges from 16 -> 20 as time goes on
DISCORD_GUILD_ID_MIN_LENGTH = 17  # ranges from 17 -> 20 as time goes on

MEETING_UUID_LENGTH = 16  # fixed length for meeting UUIDs


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


def get_current_timestamp_est() -> datetime:
    """Get the current EST timestamp."""
    return datetime.now(ZoneInfo("America/New_York"))


def calculate_file_sha256(file_path: str) -> str:
    """Calculate the SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def calculate_audio_file_duration_ms(file_path: str) -> int:
    """Calculate the duration of an audio file in milliseconds."""
    ffprobe_executable = os.environ.get(
        (
            "WINDOWS_FFPROBE_PATH"
            if platform.system().lower().startswith("win")
            else "MAC_FFPROBE_PATH"
        ),
        "ffprobe",
    )

    command = [
        ffprobe_executable,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]

    try:
        output = subprocess.check_output(command, stderr=subprocess.STDOUT)
        duration = float(output)
        return int(duration * 1000)  # Convert to milliseconds
    except subprocess.CalledProcessError as e:
        print(f"Error occurred while calculating audio file duration: {e}")
        return 0
