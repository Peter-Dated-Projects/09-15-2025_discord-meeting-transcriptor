import hashlib
import logging
import os
import platform
import subprocess
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

logger = logging.getLogger(__name__)

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


async def calculate_file_sha256(file_path: str) -> str:
    """Calculate the SHA256 hash of a file."""
    import asyncio

    def _hash_file():
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read and update hash string value in blocks of 4K
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _hash_file)


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


# -------------------------------------------------------------- #
# Bot Utilities
# -------------------------------------------------------------- #


class BotUtils:
    """Utility class for Discord bot operations."""

    @staticmethod
    async def send_dm(
        bot_instance: discord.Bot,
        user_id: int | str,
        message: str,
        embed: discord.Embed | None = None,
    ) -> bool:
        """
        Send a direct message to a Discord user.

        Args:
            bot_instance: Discord bot instance
            user_id: Discord user ID (int or string)
            message: Message content to send
            embed: Optional embed to include in the message

        Returns:
            True if message was sent successfully, False otherwise
        """
        try:
            user = await bot_instance.fetch_user(int(user_id))
            if not user:
                logger.warning(f"Could not fetch user {user_id}")
                return False

            if embed:
                await user.send(content=message, embed=embed)
            else:
                await user.send(message)

            logger.info(f"Successfully sent DM to user {user_id}")
            return True

        except discord.Forbidden:
            logger.warning(f"Could not send DM to user {user_id} - DMs disabled or bot blocked")
            return False
        except discord.HTTPException as e:
            logger.error(f"HTTP error sending DM to user {user_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error sending DM to user {user_id}: {e}")
            return False

    @staticmethod
    async def send_bulk_dms(
        bot_instance: discord.Bot,
        user_ids: list[int | str],
        message: str,
        embed: discord.Embed | None = None,
    ) -> dict[str, int]:
        """
        Send a direct message to multiple Discord users.

        Args:
            bot_instance: Discord bot instance
            user_ids: List of Discord user IDs
            message: Message content to send
            embed: Optional embed to include in the message

        Returns:
            Dictionary with counts: {'success': int, 'failed': int}
        """
        results = {"success": 0, "failed": 0}

        for user_id in user_ids:
            success = await BotUtils.send_dm(bot_instance, user_id, message, embed)
            if success:
                results["success"] += 1
            else:
                results["failed"] += 1

        logger.info(
            f"Bulk DM send complete: {results['success']} successful, {results['failed']} failed"
        )
        return results
