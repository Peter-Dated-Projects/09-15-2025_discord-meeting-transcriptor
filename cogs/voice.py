import discord
from discord import app_commands
from discord.ext import commands


class Voice(commands.Cog):
    """Voice based commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------- #
    # Slash Commands
    # -------------------------------------------------------------- #


async def setup(bot: commands.Bot):
    await bot.add_cog(Voice(bot))
