import asyncio
import logging
import os

import discord
from discord.ext import commands

from source.server.server import ServerManager
from source.services.discord_recorder.manager import DiscordSessionHandler
from source.services.manager import ServicesManager

logger = logging.getLogger(__name__)


# -------------------------------------------------------------- #
# Cog
# -------------------------------------------------------------- #


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

    async def on_voice_state_update(self, member, before, after):
        """Handle voice state updates for members.

        Args:
            member: The member whose voice state has changed
            before: The previous voice state
            after: The new voice state
        """

        # TODO - if there's no use for this, then remove it
        # # Log voice state changes
        # logger.info(
        #     f"Voice state update for member {member.id}: "
        #     f"before={before.channel.id if before.channel else 'None'}, "
        #     f"after={after.channel.id if after.channel else 'None'}"
        # )

        pass

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

        # Debug logging
        logger.info(
            f"Transcribe command called by {ctx.author.id} in guild {ctx.guild.id if ctx.guild else 'DM'}"
        )
        logger.info(f"ctx.author.voice: {ctx.author.voice}")
        if ctx.author.voice:
            logger.info(f"Voice channel: {ctx.author.voice.channel}")

        if not voice_channel:
            await ctx.edit(content="❌ You must be in a voice channel to use this command.")
            return

        # 2. Connect to voice channel with robust error handling
        await ctx.edit(content="⏳ Connecting to voice channel...")
        voice_client = await voice_channel.connect(timeout=5.0, reconnect=True)

        # 3. Start recording session
        await ctx.edit(content="🎙️ Starting recording...")

        # Check if discord_recorder_service_manager is available
        if not self.services.discord_recorder_service_manager:
            await ctx.edit(content="❌ Recording service is not available.")
            await voice_client.disconnect()
            return

        # Start recording with required parameters
        session_instance = await self.services.discord_recorder_service_manager.start_session(
            discord_voice_client=voice_client,
            channel_id=voice_channel.id,
            user_id=str(ctx.author.id),
            guild_id=str(ctx.guild.id),
            bot_instance=self.bot,
        )

        if not session_instance:
            await ctx.edit(content="❌ Failed to start recording session.")
            await voice_client.disconnect()
            return

        # Cache within the active sessions
        self.services.discord_recorder_service_manager.sessions[voice_channel.id] = session_instance

        await ctx.edit(content="✅ Recording started! Use /stop to end the transcription.")

    @commands.slash_command(name="stop", description="Stop transcribing the current voice channel")
    async def stop(self, ctx: discord.ApplicationContext) -> None:
        """Stop transcribing the voice channel the user is currently in.

        Args:
            ctx: Discord application context
        """
        await ctx.defer()
        await ctx.edit(content="⏳ Stopping transcription...")

        # 1. Validate user is in a voice channel
        voice_channel = self.find_user_vc(ctx)
        if not voice_channel:
            await ctx.edit(content="❌ You must be in a voice channel to use this command.")
            return

        # 2. Check if bot is connected to voice channel
        voice_client = await self.get_bot_voice_client(ctx)
        if not voice_client or voice_client.channel.id != voice_channel.id:
            await ctx.edit(content="❌ The bot is not connected to your voice channel.")
            return

        # 3. Verify active recording session exists
        session = self.services.discord_recorder_service_manager.get_active_session(
            voice_channel.id
        )
        if not session:
            await ctx.edit(content="❌ No active recording session found.")
            logger.warning(f"No active recording session found for channel {voice_channel.id}")
            return

        meeting_id = session.meeting_id
        logger.info(
            f"Stopping recording session: meeting_id={meeting_id}, channel={voice_channel.id}"
        )

        # 4. Check if discord_recorder_service_manager is available
        if not self.services.discord_recorder_service_manager:
            await ctx.edit(content="❌ Recording service is not available.")
            return

        # 5. Stop recording session (handles transcoding, concatenation, SQL updates, and DMs)
        await ctx.edit(content="⏳ Stopping recording and processing audio...")
        await self.services.discord_recorder_service_manager.stop_session(
            channel_id=voice_channel.id, bot_instance=self.bot
        )
        logger.info(f"Recording session stopped for meeting {meeting_id}")

        # 6. Disconnect from voice channel
        await ctx.followup.send(
            "✅ Recording stopped! Audio files are being processed in the background.\n"
            "You will receive a DM when your recording is ready.",
            ephemeral=True,
        )

        try:
            if voice_client.is_connected():
                await voice_client.disconnect()
                logger.info(f"Disconnected from {voice_channel.name}")

            # Remove from active sessions cache
            self.services.discord_recorder_service_manager.sessions.pop(voice_channel.id, None)
        except Exception as e:
            logger.error(f"Error disconnecting from voice: {e}")

        return

    # -------------------------------------------------------------- #
    # Debug Functions
    # -------------------------------------------------------------- #

    @commands.slash_command(
        name="debug_active_sessions", description="Debug: List active recording sessions"
    )
    async def debug_active_sessions(self, ctx: discord.ApplicationContext) -> None:
        """List all active recording sessions."""
        sessions = self.services.discord_recorder_service_manager.sessions
        if len(sessions) == 0:
            await ctx.send("No active recording sessions found.")
            return

        session_list = []
        for channel_id, session in sessions.items():
            session_list.append(f"Channel ID: {channel_id}, Meeting ID: {session.meeting_id}")

        await ctx.edit("Active recording sessions:\n" + "\n".join(session_list))


def setup(bot: discord.Bot, server: ServerManager, services: ServicesManager):
    voice = Voice(bot, server, services)
    bot.add_cog(voice)

    # -------------------------------------------------------------- #
    # Add listeners
    # -------------------------------------------------------------- #

    bot.add_listener(voice.on_voice_state_update, "on_voice_state_update")
