# Main File

import logging
import os
import sys

import discord
import dotenv
from discord.ext import commands

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager

dotenv.load_dotenv(dotenv_path=".env.local")

# Configure logging to output to console (stdout) with proper formatting
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,  # Override any existing configuration
)

# -------------------------------------------------------------- #
# Discord Bot Setup
# -------------------------------------------------------------- #

# Add your Discord server ID(s) here for instant command registration during development
# You can find your server ID by right-clicking your server icon with Developer Mode enabled
DEBUG_GUILD_IDS = [1233459903696208014]  # Example: [123456789012345678]
# Leave empty [] for global commands (takes up to 1 hour to register)
# Or add your guild IDs for instant registration during development

intents = discord.Intents.default()
intents.voice_states = True

# If DEBUG_GUILD_IDS is not empty, commands will register instantly in those guilds
bot = discord.Bot(intents=intents, debug_guilds=DEBUG_GUILD_IDS)


def load_cogs(servers_manager, services_manager):
    """Load all cog extensions with server and services managers.

    Args:
        servers_manager: The server manager instance
        services_manager: The services manager instance
    """
    from cogs.general import setup as setup_general
    from cogs.voice import setup as setup_voice

    setup_general(bot, servers_manager, services_manager)
    print("✓ Loaded cogs.general")

    setup_voice(bot, servers_manager, services_manager)
    print("✓ Loaded cogs.voice")


# -------------------------------------------------------------- #
# Events
# -------------------------------------------------------------- #


@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("------")

    # In py-cord, slash commands are automatically synced
    # No manual syncing needed like discord.py's tree.sync()
    print("Bot is ready! Slash commands are automatically available.")
    print(f"Connected to {len(bot.guilds)} guild(s):")
    for guild in bot.guilds:
        print(f"  ✓ {guild.name} (ID: {guild.id})")

    # Display all registered slash commands
    print("\nRegistered slash commands:")
    slash_commands = [
        cmd for cmd in bot.pending_application_commands if isinstance(cmd, discord.SlashCommand)
    ]
    if slash_commands:
        for cmd in slash_commands:
            print(f"  ✓ /{cmd.name} - {cmd.description}")
    else:
        print("  (No slash commands registered)")

    # Important information about command visibility
    if DEBUG_GUILD_IDS:
        print(f"\n⚠️  Commands registered for guilds: {DEBUG_GUILD_IDS}")
        print("   Commands should appear INSTANTLY in these servers.")
    else:
        print("\n⚠️  Commands registered GLOBALLY")
        print("   ⏱️  This can take up to 1 HOUR to appear in Discord!")
        print("   💡 TIP: Set DEBUG_GUILD_IDS for instant registration during development")


@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    """Handle errors in application commands."""
    logging.error(f"Error in command {ctx.command.name}: {error}")

    if isinstance(error, discord.CheckFailure):
        await ctx.respond("❌ You don't have permission to use this command.", ephemeral=True)
    else:
        await ctx.respond(f"❌ An error occurred: {str(error)}", ephemeral=True)


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
        load_cogs(servers_manager, services_manager)
        token = os.getenv("DISCORD_API_TOKEN")
        if not token:
            print("Error: DISCORD_API_TOKEN not found in environment variables")
            return
        await bot.start(token)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
