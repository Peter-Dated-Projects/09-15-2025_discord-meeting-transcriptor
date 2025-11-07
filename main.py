# Main File

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Configure Python's built-in logging for server initialization
# (before AsyncLoggingService is available)
logs_dir = Path("logs")
logs_dir.mkdir(parents=True, exist_ok=True)
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_file = logs_dir / f"app_{timestamp}.log"

# Configure logging to output to both console and file
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, mode="a", encoding="utf-8"),
    ],
    force=True,
)

# -------------------------------------------------------------- #
# Imports
# -------------------------------------------------------------- #

import discord
import dotenv

from source.constructor import ServerManagerType
from source.context import Context
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager

dotenv.load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Discord Bot Setup
# -------------------------------------------------------------- #

# Add your Discord server ID(s) here for instant command registration during development
# You can find your server ID by right-clicking your server icon with Developer Mode enabled
DEBUG_GUILD_IDS = [1233459903696208014, 1266931275047108691]  # Example: [123456789012345678]
# Leave empty [] for global commands (takes up to 1 hour to register)
# Or add your guild IDs for instant registration during development

intents = discord.Intents.default()
intents.voice_states = True

# If DEBUG_GUILD_IDS is not empty, commands will register instantly in those guilds
bot = discord.Bot(intents=intents, debug_guilds=DEBUG_GUILD_IDS)


async def load_cogs(context: Context):
    """Load all cog extensions with context.

    Args:
        context: The application context instance
    """
    from cogs.general import setup as setup_general
    from cogs.voice import setup as setup_voice

    setup_general(context)
    await context.services_manager.logging_service.info("✓ Loaded cogs.general")

    setup_voice(context)
    await context.services_manager.logging_service.info("✓ Loaded cogs.voice")


# -------------------------------------------------------------- #
# Commands
# -------------------------------------------------------------- #


@bot.command(name="murder", description="Stops the bot for real")
async def murder(ctx: discord.ApplicationContext):
    """Stop the bot."""
    await ctx.respond("🔪 Stopping the bot...")
    await bot.close()


# -------------------------------------------------------------- #
# Events
# -------------------------------------------------------------- #


@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logger = bot.context.services_manager.logging_service

    await logger.info(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    await logger.info("------")

    # In py-cord, slash commands are automatically synced
    # No manual syncing needed like discord.py's tree.sync()
    await logger.info("Bot is ready! Slash commands are automatically available.")
    await logger.info(f"Connected to {len(bot.guilds)} guild(s):")
    for guild in bot.guilds:
        await logger.info(f"  ✓ {guild.name} (ID: {guild.id})")

    # Display all registered slash commands
    await logger.info("\nRegistered slash commands:")
    slash_commands = [
        cmd for cmd in bot.pending_application_commands if isinstance(cmd, discord.SlashCommand)
    ]
    if slash_commands:
        for cmd in slash_commands:
            await logger.info(f"  ✓ /{cmd.name} - {cmd.description}")
    else:
        await logger.info("  (No slash commands registered)")

    # Important information about command visibility
    if DEBUG_GUILD_IDS:
        await logger.info(f"\n⚠️  Commands registered for guilds: {DEBUG_GUILD_IDS}")
        await logger.info("   Commands should appear INSTANTLY in these servers.")
    else:
        await logger.info("\n⚠️  Commands registered GLOBALLY")
        await logger.info("   ⏱️  This can take up to 1 HOUR to appear in Discord!")
        await logger.info(
            "   💡 TIP: Set DEBUG_GUILD_IDS for instant registration during development"
        )


@bot.event
async def on_application_command_error(
    ctx: discord.ApplicationContext, error: discord.DiscordException
):
    """Handle errors in application commands."""
    logger = bot.context.services_manager.logging_service
    await logger.error(f"Error in command {ctx.command.name}: {error}")

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

    # We need to print to console initially since logging service isn't set up yet
    print("=" * 40)
    print("Syncing services...")

    # Create context object
    context = Context()

    # init server manager
    servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
    context.set_server_manager(servers_manager)
    await servers_manager.connect_all()
    print("[OK] Connected all servers.")

    storage_path = os.path.join("assets", "data")
    recording_storage_path = os.path.join(storage_path, "recordings")

    # Use the same log file that was created for built-in logging
    services_manager = construct_services_manager(
        ServerManagerType.DEVELOPMENT,
        context=context,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
        log_file=log_file.name,  # Use the same log file
    )
    context.set_services_manager(services_manager)
    await services_manager.initialize_all()

    # Now we can use the async logger
    logger = services_manager.logging_service
    await logger.info("[OK] Initialized all services.")

    # Set bot instance on context
    context.set_bot(bot)

    # Store context on bot for access in cogs
    bot.context = context

    # -------------------------------------------------------------- #
    # Start Discord Bot
    # -------------------------------------------------------------- #

    async with bot:
        await load_cogs(context)
        token = os.getenv("DISCORD_API_TOKEN")
        if not token:
            await logger.error("Error: DISCORD_API_TOKEN not found in environment variables")
            return
        await bot.start(token)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
