import logging

import discord
from discord.ext import commands

from source.context import Context

logger = logging.getLogger(__name__)


# -------------------------------------------------------------- #
# Cog
# -------------------------------------------------------------- #


class Chat(commands.Cog):
    """Chat-based interaction commands and listeners."""

    def __init__(self, context: Context):
        self.context = context
        # Backward compatibility properties
        self.bot = context.bot
        self.server = context.server_manager
        self.services = context.services_manager

    # -------------------------------------------------------------- #
    # Event Listeners
    # -------------------------------------------------------------- #

    async def on_message(self, message: discord.Message):
        """Handle messages where the bot is mentioned.
        
        When the bot is pinged in a guild, this handler:
        1. Grabs information about the guild, message context, etc.
        2. Creates a thread from the message
        3. Sends "Echo is thinking…" in the thread
        
        Args:
            message: The Discord message object
        """
        # Ignore messages from the bot itself
        if message.author.bot:
            return

        # Check if the bot is mentioned
        if self.bot.user not in message.mentions:
            return

        # Only respond in guilds (not DMs)
        if not message.guild:
            return

        try:
            # Gather message and guild information
            guild_id = message.guild.id
            guild_name = message.guild.name
            channel_id = message.channel.id
            channel_name = message.channel.name if hasattr(message.channel, 'name') else "Unknown"
            message_id = message.id
            author_id = message.author.id
            author_name = str(message.author)
            message_content = message.content
            
            # Log the interaction details
            await self.services.logging_service.info(
                f"Bot mentioned in guild '{guild_name}' ({guild_id}) "
                f"by {author_name} ({author_id}) "
                f"in #{channel_name} ({channel_id})"
            )
            await self.services.logging_service.debug(
                f"Message ID: {message_id}, Content: {message_content[:100]}..."
            )

            # Create a thread from the message
            thread_name = f"Chat with {message.author.name}"
            
            # Check if message is already in a thread
            if isinstance(message.channel, discord.Thread):
                thread = message.channel
                await self.services.logging_service.info(
                    f"Message already in thread: {thread.name} ({thread.id})"
                )
            else:
                # Create a new thread from the message
                thread = await message.create_thread(
                    name=thread_name,
                    auto_archive_duration=60  # Archive after 1 hour of inactivity
                )
                await self.services.logging_service.info(
                    f"Created thread: {thread.name} ({thread.id})"
                )

            # Send "Echo is thinking…" message in the thread
            await thread.send("Echo is thinking…")
            
            await self.services.logging_service.info(
                f"Sent thinking message in thread {thread.id}"
            )

        except discord.Forbidden:
            await self.services.logging_service.error(
                f"Missing permissions to create thread or send message in guild {message.guild.id}"
            )
        except discord.HTTPException as e:
            await self.services.logging_service.error(
                f"HTTP error while handling message {message.id}: {e}"
            )
        except Exception as e:
            await self.services.logging_service.error(
                f"Unexpected error handling bot mention: {e}",
                exc_info=True
            )


def setup(context: Context):
    chat = Chat(context)
    context.bot.add_cog(chat)
    
    # -------------------------------------------------------------- #
    # Add listeners
    # -------------------------------------------------------------- #
    
    context.bot.add_listener(chat.on_message, "on_message")
