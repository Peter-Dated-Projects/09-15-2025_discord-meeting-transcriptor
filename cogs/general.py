import discord
from discord.ext import commands

from source.context import Context


class General(commands.Cog):
    """General purpose commands."""

    def __init__(self, context: Context):
        self.context = context
        # Backward compatibility properties
        self.bot = context.bot
        self.server = context.server_manager
        self.services = context.services_manager

    # -------------------------------------------------------------- #
    # Slash Commands
    # -------------------------------------------------------------- #

    @commands.slash_command(name="whoami", description="Display information about the bot")
    async def whoami(self, ctx: discord.ApplicationContext):
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
            text=f"Requested by {ctx.author.name}",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else None,
        )

        # Send the embed as a response
        await ctx.respond(embed=embed)


def setup(context: Context):
    general = General(context)
    context.bot.add_cog(general)
