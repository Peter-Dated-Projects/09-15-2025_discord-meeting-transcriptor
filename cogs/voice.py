import asyncio
import logging

import discord
from discord.ext import commands

from source.server.server import ServerManager
from source.services.manager import ServicesManager

logger = logging.getLogger(__name__)


class VoiceConnectionError(Exception):
    """Base exception for voice connection errors."""

    pass


class Voice(commands.Cog):
    """Voice based commands."""

    def __init__(self, bot: discord.Bot, server: ServerManager, services: ServicesManager):
        self.bot = bot
        self.server = server
        self.services = services

    # -------------------------------------------------------------- #
    # Utils
    # -------------------------------------------------------------- #

    def find_user_vc(self, ctx: discord.ApplicationContext) -> discord.VoiceChannel | None:
        """Find a voice channel the user is in.

        Args:
            ctx: Discord application context

        Returns:
            Voice channel if user is connected, None otherwise
        """
        return ctx.author.voice.channel if ctx.author.voice else None

    async def get_bot_voice_client(
        self,
        ctx: discord.ApplicationContext,
    ) -> discord.VoiceClient | None:
        """Get the bot's voice client in a guild, if connected.

        Args:
            ctx: Discord application context

        Returns:
            Voice client if bot is connected in this guild, None otherwise
        """
        if ctx.guild is None:
            return None

        client = ctx.guild.voice_client

        # Has existing connection
        if client and client.is_connected():
            return client
        return None

    async def connect_to_vc(
        self,
        ctx: discord.ApplicationContext,
        target_channel: discord.VoiceChannel,
    ) -> tuple[discord.VoiceClient | None, str | None]:
        """Connect to a voice channel with robust error handling.

        Args:
            ctx: Discord application context
            target_channel: Voice channel to connect to

        Returns:
            Tuple of (VoiceClient or None, Error message or None)
        """
        if ctx.guild is None:
            return None, "This command can only be used in a guild."

        try:
            voice_client = ctx.guild.voice_client

            # Check if bot is in call already
            if voice_client and voice_client.is_connected():
                # If user in same call
                if voice_client.channel.id == target_channel.id:
                    return voice_client, None

                # Move to new channel
                await voice_client.disconnect(force=True)
                await asyncio.sleep(0.2)
                await voice_client.move_to(target_channel)
                return voice_client, None

            # Not connected - establish new connection
            voice_client = await target_channel.connect()
            return voice_client, None
        except discord.DiscordException as e:
            return None, f"Failed to connect to voice channel: {e}"

    # -------------------------------------------------------------- #
    # Slash Commands
    # -------------------------------------------------------------- #

    @commands.slash_command(name="transcribe", description="Transcribe the current voice channel")
    async def transcribe(self, ctx: discord.ApplicationContext) -> None:
        """Start transcribing the voice channel the user is currently in.

        Args:
            ctx: Discord application context
        """
        await ctx.defer()
        await ctx.edit(content="⏳ Joining Discord Call...")

        # 1. Validate user is in a voice channel
        voice_channel = self.find_user_vc(ctx)
        if not voice_channel:
            await ctx.edit(content="❌ You must be in a voice channel to use this command.")
            return

        # 2. Connect to voice channel with robust error handling
        await ctx.edit(content="⏳ Connecting to voice channel...")
        voice_client = await voice_channel.connect(timeout=5.0, reconnect=True)

        # TODO - implement transcription logic + recording service
        # This is where you'll call: voice_client.start_recording(...)

        # Temporary: wait 5 seconds then disconnect
        await ctx.edit(content="✅ Transcription started! (simulated for 5 seconds)")
        await asyncio.sleep(5)

        # 4. Clean disconnect
        await ctx.followup.send(
            "🛑 Stopping transcription and leaving voice channel.", ephemeral=True
        )

        try:
            if voice_client.is_connected():
                await voice_client.disconnect()
                logger.info(f"Disconnected from {voice_channel.name}")
        except Exception as e:
            logger.error(f"Error disconnecting from voice: {e}")

        return


def setup(bot: discord.Bot, server: ServerManager, services: ServicesManager):
    bot.add_cog(Voice(bot, server, services))
