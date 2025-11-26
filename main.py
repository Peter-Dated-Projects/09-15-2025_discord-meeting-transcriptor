# Main File

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import discord
import dotenv

from source.constructor import ServerManagerType
from source.context import Context
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager

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

dotenv.load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Discord Bot Setup
# -------------------------------------------------------------- #

# Add your Discord server ID(s) here for instant command registration during development
# You can find your server ID by right-clicking your server icon with Developer Mode enabled
DEBUG_GUILD_IDS = [
    1233459903696208014,
    1266931275047108691,
    1235590570773057566,
    1391829654847094975,  # homeless shelter
]  # Example: [123456789012345678]
# Leave empty [] for global commands (takes up to 1 hour to register)
# Or add your guild IDs for instant registration during development

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True  # Required for reading message content and detecting mentions

# If DEBUG_GUILD_IDS is not empty, commands will register instantly in those guilds
bot = discord.Bot(intents=intents, debug_guilds=DEBUG_GUILD_IDS)


# -------------------------------------------------------------- #
# Event Handler System
# -------------------------------------------------------------- #
#
# This implements a filter-based event handling architecture where:
# 1. Each cog can register event handlers with filters
# 2. Filters determine if a handler should process an event
# 3. By default, handlers are "pass-through" - they allow subsequent handlers to run
# 4. Handlers can return False or be configured with pass_through=False to stop propagation
#
# Benefits:
# - Separation of concerns: each cog handles its own filtering logic
# - Composable: multiple handlers can process the same event
# - Flexible: handlers can be chained, ordered, or isolated as needed
# - Maintainable: adding new handlers doesn't require modifying main.py
#


class MessageEventHandler:
    """Handler for message events with a filter-based architecture.

    Handlers are registered with filters that determine if they should process
    a message. By default, handlers pass through (allow subsequent handlers to run).
    """

    def __init__(self):
        self.handlers = []

    def register_handler(self, filter_func, handler_func, pass_through: bool = True):
        """Register a message event handler with a filter.

        Args:
            filter_func: Async function that takes a message and returns bool
                        (True if handler should process the message)
            handler_func: Async function that processes the message
            pass_through: If True, continue to next handler after this one.
                         If False, stop propagation after this handler.
        """
        self.handlers.append(
            {"filter": filter_func, "handler": handler_func, "pass_through": pass_through}
        )

    async def process_message(self, message: discord.Message):
        """Process a message through all registered handlers.

        Args:
            message: The Discord message to process
        """
        for handler_info in self.handlers:
            try:
                # Check if the filter passes
                if await handler_info["filter"](message):
                    # Execute the handler
                    result = await handler_info["handler"](message)

                    # Check if we should continue to next handler
                    # If handler returns False or pass_through is False, stop
                    if not handler_info["pass_through"] or result is False:
                        break
            except Exception as e:
                # Log error but continue to next handler
                logging.error(f"Error in message handler: {e}", exc_info=True)


# Create global message event handler
message_event_handler = MessageEventHandler()


async def load_cogs(context: Context):
    """Load all cog extensions with context.

    Args:
        context: The application context instance
    """
    from cogs.general import setup as setup_general
    from cogs.voice import setup as setup_voice
    from cogs.chat import setup as setup_chat

    setup_general(context)
    await context.services_manager.logging_service.info("✓ Loaded cogs.general")

    setup_voice(context)
    await context.services_manager.logging_service.info("✓ Loaded cogs.voice")

    # Load chat cog and register its message handler
    chat_cog = setup_chat(context)
    message_event_handler.register_handler(
        filter_func=chat_cog.filter_message,
        handler_func=chat_cog.handle_message,
        pass_through=True,  # Allow other handlers to process after this one
    )
    await context.services_manager.logging_service.info("✓ Loaded cogs.chat")
    await context.services_manager.logging_service.info("✓ Registered chat message handler")

    # Example: To add more message handlers from other cogs:
    # other_cog = setup_other(context)
    # message_event_handler.register_handler(
    #     filter_func=other_cog.filter_message,
    #     handler_func=other_cog.handle_message,
    #     pass_through=True  # or False to stop propagation
    # )


# -------------------------------------------------------------- #
# Commands
# -------------------------------------------------------------- #


@bot.command(name="murder", description="Stops the bot for real")
async def murder(ctx: discord.ApplicationContext):
    """Stop the bot gracefully, waiting for all backend services to complete."""

    # Only work if user is developer
    info = await bot.application_info()
    if (
        info.team
        and ctx.author.id not in [member.id for member in info.team.members]
        or ctx.author.id != info.owner.id
    ):
        await ctx.respond("❌ You do not have permission to use this command.")
        return

    await ctx.respond(
        "🔪 Initiating graceful shutdown... Please wait for all services to complete."
    )

    # Get the logger from context (with safety checks)
    try:
        if not bot.context or not bot.context.services_manager:
            await ctx.followup.send("⚠️ Bot context not initialized properly. Forcing shutdown...")
            await bot.close()
            return

        logger = bot.context.services_manager.logging_service
        await logger.info(f"Shutdown initiated by user: {ctx.author.name} ({ctx.author.id})")

        # Perform graceful shutdown of all services
        await bot.context.services_manager.shutdown_all(timeout=60.0)
        await ctx.followup.send(
            "✅ All services have been shut down successfully. Bot stopping now..."
        )
    except Exception as e:
        # Try to send error message to user
        import contextlib

        with contextlib.suppress(Exception):
            await ctx.followup.send(f"⚠️ Shutdown completed with errors: {str(e)}")

    # Finally, close the bot
    await bot.close()


# -------------------------------------------------------------- #
# Events
# -------------------------------------------------------------- #


@bot.event
async def on_message(message: discord.Message):
    """Global message event handler that routes messages through registered handlers.

    This handler runs all messages through the MessageEventHandler system,
    which applies filters and passes messages to appropriate cog handlers.

    Args:
        message: The Discord message object
    """
    # Process the message through the handler chain
    await message_event_handler.process_message(message)


async def _ensure_guild_subscription_and_collection(guilds: list[discord.Guild]) -> None:
    """
    Ensure all provided guilds have entries in the subscriptions table and ChromaDB collections.

    Args:
        guilds: List of Discord Guild objects to process
    """
    logger = bot.context.services_manager.logging_service
    subscription_service = bot.context.services_manager.subscription_sql_manager
    vector_db_client = bot.context.server_manager.vector_db_client

    from source.server.sql_models import SubscriptionType

    for guild in guilds:
        guild_id = str(guild.id)
        collection_name = f"embeddings_{guild_id}"

        try:
            # Check if guild already has a subscription entry
            existing_subscription = await subscription_service.search_subscription(guild_id)

            if existing_subscription:
                await logger.debug(
                    f"Guild '{guild.name}' (ID: {guild_id}) already has subscription entry"
                )
            else:
                # Create subscription entry
                await logger.info(
                    f"Creating subscription entry for guild '{guild.name}' (ID: {guild_id})"
                )
                await subscription_service.insert_subscription(
                    discord_server_id=guild_id,
                    chroma_collection_name=collection_name,
                    subscription_type=SubscriptionType.FREE,
                )
                await logger.info(f"✓ Created subscription entry for guild: {guild.name}")

            # Check if ChromaDB collection exists
            collection_exists = await vector_db_client.collection_exists(collection_name)

            if collection_exists:
                await logger.debug(
                    f"ChromaDB collection '{collection_name}' already exists for guild: {guild.name}"
                )
            else:
                # Create ChromaDB collection
                await logger.info(
                    f"Creating ChromaDB collection '{collection_name}' for guild: {guild.name}"
                )
                await vector_db_client.create_collection(collection_name)
                await logger.info(f"✓ Created ChromaDB collection: {collection_name}")

        except Exception as e:
            await logger.error(f"Failed to initialize guild '{guild.name}' (ID: {guild_id}): {e}")


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

    # Initialize guilds: ensure all guilds have subscriptions and ChromaDB collections
    await logger.info("\n" + "=" * 60)
    await logger.info("Initializing guild subscriptions and ChromaDB collections...")
    await _ensure_guild_subscription_and_collection(bot.guilds)
    await logger.info("✓ Guild initialization complete")
    await logger.info("=" * 60)

    # Initialize bot presence
    if bot.context.services_manager.presence_manager_service:
        await bot.context.services_manager.presence_manager_service.force_update_presence()
        await logger.info("✓ Bot presence initialized")


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


@bot.event
async def on_guild_join(guild: discord.Guild):
    """
    Called when the bot joins a new guild (server).
    Ensures the guild has a subscription entry and ChromaDB collection.
    """
    logger = bot.context.services_manager.logging_service

    await logger.info(f"Bot joined new guild: '{guild.name}' (ID: {guild.id})")

    # Initialize guild subscription and ChromaDB collection
    await _ensure_guild_subscription_and_collection([guild])

    await logger.info(f"✓ Successfully initialized guild: {guild.name}")


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
    transcription_storage_path = os.getenv(
        "TRANSCRIPTION_STORAGE_PATH", "assets/data/transcriptions"
    )

    # Use the same log file that was created for built-in logging
    services_manager = construct_services_manager(
        ServerManagerType.DEVELOPMENT,
        context=context,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
        transcription_storage_path=transcription_storage_path,
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
