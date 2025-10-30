import discord
from discord import app_commands
from discord.ext import commands


class Voice(commands.Cog):
    """Voice based commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------- #
    # Utils
    # -------------------------------------------------------------- #

    def find_user_vc(
        self, interaction: discord.Interaction
    ) -> discord.VoiceChannel | None:
        """Find a voice channel the user is in."""
        user = interaction.user
        channel = user.voice.channel
        return channel if channel else None

    async def get_bot_voice_client(
        self,
        interaction: discord.Interaction,
        timeout: float = 8.0,
        reconnect: bool = True,
    ) -> discord.VoiceClient | None:
        """Get the bot's voice client in a guild, if connected."""
        if interaction.guild is None:
            return None

        client = interaction.guild.voice_client

        # Has existing connection
        if client and client.is_connected():
            return client
        return None

    async def connect_to_vc(
        self,
        interaction: discord.Interaction,
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

    @app_commands.command(
        name="transcribe", description="Transcribe the current voice channel"
    )
    async def transcribe(self, interaction: discord.Interaction) -> None:
        voice_channel = self.find_user_vc(interaction)

        if not voice_channel:
            await interaction.response.send_message(
                "You must be in a voice channel to use this command.", ephemeral=True
            )
            return None

        # Join the user VC
        voice_client = await self.get_bot_voice_client(interaction)
        if not voice_client:
            voice_client = await self.connect_to_vc(interaction, voice_channel)
            await interaction.response.send_message(
                f"Joined voice channel: {voice_channel.name}", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"Already transcribing in {voice_channel.name}.", ephemeral=True
            )

        # TODO - implement transcription logic + recording service

        # wait 5 seconds then dc
        await discord.utils.sleep_until(
            discord.utils.utcnow() + discord.utils.timedelta(seconds=5)
        )
        await voice_client.disconnect()

        return None


async def setup(bot: commands.Bot):
    await bot.add_cog(Voice(bot))
