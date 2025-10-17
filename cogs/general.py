import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    """General purpose commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------- #
    # Slash Commands
    # -------------------------------------------------------------- #

    @app_commands.command(
        name="whoami", description="Display information about the bot"
    )
    async def whoami(self, interaction: discord.Interaction):
        """Display bot information with an embed."""

        # Create embed with bot information
        embed = discord.Embed(
            title=self.bot.user.name,
            description=(
                self.bot.user.bio
                if hasattr(self.bot.user, "bio") and self.bot.user.bio
                else "A Discord bot for meeting transcription"
            ),
            color=discord.Color.blue(),
        )

        # Set the bot's avatar as the embed image
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        # Add additional information
        embed.add_field(name="Bot ID", value=self.bot.user.id, inline=True)
        embed.add_field(
            name="Created At",
            value=discord.utils.format_dt(self.bot.user.created_at, style="D"),
            inline=True,
        )

        # Set footer
        embed.set_footer(
            text=f"Requested by {interaction.user.name}",
            icon_url=interaction.user.avatar.url if interaction.user.avatar else None,
        )

        # Send the embed as a response
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
