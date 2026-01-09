import logging
import asyncio
import discord
from discord.ext import commands
from source.context import Context

logger = logging.getLogger(__name__)


class Reels(commands.Cog):
    def __init__(self, context: Context):
        self.context = context
        self.bot = context.bot
        self.services = context.services_manager
        # Track active background tasks
        self._active_tasks: set[asyncio.Task] = set()

    @discord.slash_command(
        name="monitor-reels", description="Set the current channel for Instagram Reels monitoring"
    )
    @commands.has_permissions(administrator=True)
    async def monitor_reels(self, ctx: discord.ApplicationContext):
        channel_id = ctx.channel.id

        # Check if already monitored
        if self.services.instagram_reels_manager.is_channel_monitored(channel_id):
            await ctx.respond(
                "This channel is already being monitored for Instagram Reels.", ephemeral=True
            )
            return

        self.services.instagram_reels_manager.add_channel(channel_id)
        self.services.instagram_reels_manager.save_config()  # Save explicitly to be safe

        await ctx.respond(
            f"✅ Channel {ctx.channel.mention} is now being monitored for Instagram Reels.",
            ephemeral=False,
        )

    # Message handler logic
    async def filter_message(self, message: discord.Message) -> bool:
        # Check if channel is monitored
        if not self.services.instagram_reels_manager.is_channel_monitored(message.channel.id):
            return False

        if message.author.bot:
            return False

        # Skip if this message would be handled by the chat cog
        # (bot mention or in conversation thread)
        # This prevents double-processing - let the LLM handle it via tool
        if isinstance(message.channel, discord.Thread):
            thread_id = str(message.channel.id)
            if self.services.conversation_manager.is_conversation_thread(thread_id):
                return False
            if self.services.conversation_manager.is_known_thread(thread_id):
                return False

        # Skip if bot is mentioned (chat cog will handle it)
        if self.bot.user in message.mentions:
            return False

        # Only process if it has a reel URL
        # Basic check, detailed check later
        if "instagram.com" in message.content:
            return True

        return False

    async def _process_reel_async(self, message: discord.Message, url: str):
        """
        Background task to process a reel asynchronously.

        This runs independently and replies to the original message when complete.

        Args:
            message: Original Discord message containing the reel
            url: Instagram reel URL to process
        """
        import json

        guild_id = str(message.guild.id) if message.guild else "DM"
        status_msg = None

        try:
            # Send initial status message
            status_msg = await message.reply(
                "🔄 Processing Instagram Reel...", mention_author=False
            )

            # Run full analysis via manager
            data = await self.services.instagram_reels_manager.run_analysis_workflow(
                url, job_id_suffix=str(message.id)
            )

            # Log Generated Data from Reel Analysis
            logger.info(f"Reel analysis result: {json.dumps(data, indent=2)}")

            # Extract the summary from the LLM's tool call response
            summary = data.get("summary", "No summary generated")

            # Create simple embed with just the summary
            embed = discord.Embed(
                title="📱 Reel Summary",
                description=summary,
                color=discord.Color.blue(),
                url=url,
            )

            await status_msg.edit(content="", embed=embed)

            # Store reel summary in vectordb for future retrieval
            try:
                from source.services.misc.instagram_reels.storage import (
                    generate_and_store_reel_embeddings,
                )

                await generate_and_store_reel_embeddings(
                    services=self.services,
                    summary_text=summary,
                    description=data.get("description", ""),
                    reel_url=url,
                    guild_id=guild_id,
                    message_id=str(message.id),
                    message_content=message.content,
                    user_id=str(message.author.id),
                    channel_id=str(message.channel.id),
                    timestamp=message.created_at.isoformat(),
                )

                logger.info(f"Successfully stored reel embeddings for {url}")

            except Exception as storage_error:
                # Don't fail the whole operation if storage fails
                logger.error(
                    f"Failed to store reel embeddings for {url}: {storage_error}", exc_info=True
                )

        except Exception as e:
            logger.error(f"Error processing reel: {e}", exc_info=True)
            if status_msg:
                try:
                    await status_msg.edit(content=f"❌ Error processing reel: {str(e)}")
                except Exception as edit_error:
                    logger.error(f"Failed to update status message: {edit_error}")
            else:
                try:
                    await message.reply(f"❌ Error processing reel: {str(e)}", mention_author=False)
                except Exception as reply_error:
                    logger.error(f"Failed to send error message: {reply_error}")

    async def handle_message(self, message: discord.Message):
        """
        Handle incoming messages that may contain Instagram reel URLs.

        This method detects reels and launches async processing without blocking.

        Args:
            message: The Discord message to handle
        """
        import re

        content = message.content
        # Basic check to avoid processing every message
        # Regex for Instagram Reel URL
        url_match = re.search(r"(https?://www\.instagram\.com/(?:reel|p)/[\w-]+)", content)

        if not url_match:
            return

        url = url_match.group(1)
        logger.info(f"Reel detected: {url}")

        # Check if this reel has already been processed (simple in-memory check)
        guild_id = str(message.guild.id) if message.guild else "DM"
        if self.services.instagram_reels_manager.is_reel_processed(url, guild_id):
            # Reel already processed, inform user
            embed = discord.Embed(
                title="📱 Reel Already Processed",
                description="This reel has already been analyzed and stored in the database. You can search for it using the chatbot!",
                color=discord.Color.orange(),
                url=url,
            )
            await message.reply(embed=embed, mention_author=False)
            logger.info(f"Skipping already-processed reel: {url}")
            return

        # Mark as processing immediately to prevent race conditions
        self.services.instagram_reels_manager.mark_reel_processed(url, guild_id)

        # Launch async workflow and exit immediately
        task = asyncio.create_task(self._process_reel_async(message, url))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

        logger.info(f"Launched async reel processing workflow for {url}")
        # Handler exits here, workflow continues in background

    async def cog_unload(self):
        """Cleanup when cog is unloaded."""
        # Cancel all active tasks
        for task in self._active_tasks:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
            logger.info("All reel processing tasks cleaned up")


def setup(context: Context):
    cog = Reels(context)
    context.bot.add_cog(cog)
    return cog
