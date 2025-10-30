# Main File

import os
import discord
from discord import app_commands
from discord.ext import commands

import dotenv
import logging

from source import utils

dotenv.load_dotenv(dotenv_path=".env.local")

logging.basicConfig(level=logging.INFO)

# -------------------------------------------------------------- #
# Discord Bot Setup
# -------------------------------------------------------------- #

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="/", intents=intents)


async def load_cogs():
    """Load all cog extensions."""
    await bot.load_extension("cogs.general")
    print("✓ Loaded cogs.general")

    await bot.load_extension("cogs.voice")
    print("✓ Loaded cogs.voice")


# -------------------------------------------------------------- #
# Events
# -------------------------------------------------------------- #


@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")

    # Sync slash commands with Discord
    try:
        # Sync in call guilds for instant access
        print("Syncing to individual guilds for instant access...")
        for guild in bot.guilds:
            synced = await bot.tree.sync(guild=guild)
            print(
                f"  ✓ Synced {len(synced)} command(s) to: {guild.name} (ID: {guild.id})"
            )

    except Exception as e:
        print(f"Failed to sync commands: {e}")


@bot.tree.command(
    name="transcribe", description="Join an active VC and begin transcription"
)
async def transcribe(ctx: discord.Interaction):
    """Join the user's current voice channel and start transcribing."""
    if not ctx.user.voice or not ctx.user.voice.channel:
        await ctx.response.send_message(
            "You must be in a voice channel to use this command.", ephemeral=True
        )
        return

    voice_channel = ctx.user.voice.channel

    if ctx.guild.voice_client:
        await ctx.guild.voice_client.move_to(voice_channel)
    else:
        await voice_channel.connect()

    await ctx.response.send_message(
        f"Joined {voice_channel.name} and started transcribing!", ephemeral=True
    )


# -------------------------------------------------------------- #
# Run Bot
# -------------------------------------------------------------- #


async def main():
    """Main function to load cogs and start the bot."""
    async with bot:
        await load_cogs()
        token = os.getenv("DISCORD_API_TOKEN")
        if not token:
            print("Error: DISCORD_API_TOKEN not found in environment variables")
            return
        await bot.start(token)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
