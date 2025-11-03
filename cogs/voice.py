import asyncio

import discord
from discord.ext import commands


class Voice(commands.Cog):
    """Voice based commands."""

    def __init__(self, bot: discord.Bot):
        self.bot = bot

    # -------------------------------------------------------------- #
    # Utils
    # -------------------------------------------------------------- #

    def find_user_vc(self, ctx: discord.ApplicationContext) -> discord.VoiceChannel | None:
        """Find a voice channel the user is in."""
        user = ctx.author
        channel = user.voice.channel
        return channel if channel else None

    async def get_bot_voice_client(
        self,
        ctx: discord.ApplicationContext,
    ) -> discord.VoiceClient | None:
        """Get the bot's voice client in a guild, if connected."""
        if ctx.guild is None:
            return None

        client = ctx.guild.voice_client

        # Has existing connection
        if client and client.is_connected():
            return client
        return None

    async def connect_to_vc(
        self,
        channel: discord.VoiceChannel,
        timeout: float = 8.0,
        reconnect: bool = True,
    ) -> discord.VoiceClient | None:
        """Connect the bot to the user's voice channel."""
        voice_client = await channel.connect(timeout=timeout, reconnect=reconnect)
        return voice_client

    # -------------------------------------------------------------- #
    # Slash Commands
    # -------------------------------------------------------------- #

    @commands.slash_command(name="transcribe", description="Transcribe the current voice channel")
    async def transcribe(self, ctx: discord.ApplicationContext) -> None:
        voice_channel = self.find_user_vc(ctx)
        await ctx.defer(ephemeral=True)

        if not voice_channel:
            await ctx.edit(content="You must be in a voice channel to use this command.")
            return None

        # Join the user VC
        voice_client = await self.get_bot_voice_client(ctx)
        if not voice_client:
            voice_client = await self.connect_to_vc(voice_channel)
            await ctx.edit(content=f"Joined voice channel: {voice_channel.name}")
        else:
            await ctx.edit(content=f"Already transcribing in {voice_channel.name}.")

        # TODO - implement transcription logic + recording service

        # wait 5 seconds then dc
        await asyncio.sleep(5)

        await ctx.followup.send("Stopping transcription and leaving voice channel.", ephemeral=True)
        await voice_client.disconnect()

        return None


def setup(bot: discord.Bot):
    bot.add_cog(Voice(bot))
