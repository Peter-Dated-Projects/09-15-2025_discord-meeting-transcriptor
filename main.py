# Main File

import logging
import os

import discord
import dotenv
from discord.ext import commands

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager

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
        # -------------------------------------------------------------- #
        # Sync Slash Commands
        # -------------------------------------------------------------- #

        # Sync in call guilds for instant access
        print("Syncing to individual guilds for instant access...")
        for guild in bot.guilds:
            synced = await bot.tree.sync(guild=guild)
            print(f"  ✓ Synced {len(synced)} command(s) to: {guild.name} (ID: {guild.id})")

    except Exception as e:
        print(f"Failed to sync commands: {e}")


# -------------------------------------------------------------- #
# Run Bot
# -------------------------------------------------------------- #


async def main():
    """Main function to load cogs and start the bot."""
    # -------------------------------------------------------------- #
    # Startup services
    # -------------------------------------------------------------- #

    print("=" * 40)
    print("Syncing services...")

    # init server manager
    servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT)
    await servers_manager.connect_all()
    print("[OK] Connected all servers.")

    storage_path = os.path.join("assets", "data")
    recording_storage_path = os.path.join(storage_path, "recordings")

    services_manager = construct_services_manager(
        ServerManagerType.DEVELOPMENT,
        server=servers_manager,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
    )
    await services_manager.initialize_all()
    print("[OK] Initialized all services.")

    # Store services_manager on bot for access in cogs
    bot.services_manager = services_manager

    # -------------------------------------------------------------- #
    # Start Discord Bot
    # -------------------------------------------------------------- #

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
