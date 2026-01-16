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
        # Monitor the specific channel or thread the user is typing in
        channel_id = ctx.channel.id
        channel_type = "thread" if isinstance(ctx.channel, discord.Thread) else "channel"

        # Check if already monitored
        if self.services.instagram_reels_manager.is_channel_monitored(channel_id):
            await ctx.respond(
                f"This {channel_type} is already being monitored for Instagram Reels.",
                ephemeral=True,
            )
            return

        self.services.instagram_reels_manager.add_channel(channel_id)
        self.services.instagram_reels_manager.save_config()  # Save explicitly to be safe

        await ctx.respond(
            f"✅ This {channel_type} (<#{channel_id}>) is now being monitored for Instagram Reels.",
            ephemeral=False,
        )

    @discord.slash_command(
        name="disable-reels-monitoring",
        description="Disable Instagram Reels monitoring for the current channel",
    )
    @commands.has_permissions(administrator=True)
    async def disable_reels_monitoring(self, ctx: discord.ApplicationContext):
        # Disable monitoring for the specific channel or thread the user is typing in
        channel_id = ctx.channel.id
        channel_type = "thread" if isinstance(ctx.channel, discord.Thread) else "channel"

        # Check if channel is being monitored
        if not self.services.instagram_reels_manager.is_channel_monitored(channel_id):
            await ctx.respond(
                f"This {channel_type} is not currently being monitored for Instagram Reels.",
                ephemeral=True,
            )
            return

        self.services.instagram_reels_manager.remove_channel(channel_id)
        self.services.instagram_reels_manager.save_config()  # Save explicitly to be safe

        await ctx.respond(
            f"✅ Instagram Reels monitoring has been disabled for this {channel_type} (<#{channel_id}>).",
            ephemeral=False,
        )

    @discord.slash_command(
        name="reel-process-past",
        description="Process past Instagram Reels from channel history",
    )
    @commands.has_permissions(administrator=True)
    async def reel_process_past(
        self,
        ctx: discord.ApplicationContext,
        max_reels: discord.Option(
            int,
            description="Maximum number of reels to process (default: 20)",
            required=False,
            default=20,
            min_value=1,
            max_value=500,
        ) = 20,
    ):
        """
        Process past Instagram Reels from channel history.

        Paginates through messages in batches of 100, going back in time from now,
        until either max_reels are found or all messages have been checked.
        """
        await ctx.defer()

        import re

        channel = ctx.channel
        channel_type = "thread" if isinstance(channel, discord.Thread) else "channel"
        guild_id = str(ctx.guild.id) if ctx.guild else "DM"

        # Track progress
        reels_found = 0
        reels_processed = 0
        reels_skipped = 0
        messages_checked = 0
        batch_size = 100

        # Regex for Instagram Reel URL
        reel_pattern = re.compile(r"(https?://www\.instagram\.com/(?:reel|p)/[\w-]+)")

        # Send initial status
        status_msg = await ctx.followup.send(
            f"🔍 Scanning {channel_type} history for Instagram Reels...\n"
            f"Target: {max_reels} reels\n"
            f"Messages checked: 0\n"
            f"Reels found: 0",
        )

        try:
            # Paginate through message history
            async for message in channel.history(limit=None, oldest_first=False):
                messages_checked += 1

                # Update status every 100 messages
                if messages_checked % 100 == 0:
                    await status_msg.edit(
                        content=f"🔍 Scanning {channel_type} history...\n"
                        f"Target: {max_reels} reels | Found: {reels_found} | Processed: {reels_processed} | Skipped: {reels_skipped}\n"
                        f"Messages checked: {messages_checked}",
                    )

                # Skip bot messages
                if message.author.bot:
                    continue

                # Check for reel URLs
                url_match = reel_pattern.search(message.content)
                if not url_match:
                    continue

                url = url_match.group(1)
                reels_found += 1

                # Check if already processed (in-memory cache)
                if self.services.instagram_reels_manager.is_reel_processed(url, guild_id):
                    reels_skipped += 1
                    logger.info(f"Skipping already-processed reel (in-memory): {url}")
                    continue

                # Check if already exists in database (persistent check)
                from source.services.misc.instagram_reels.storage import check_reel_exists

                if await check_reel_exists(self.services, url, guild_id):
                    reels_skipped += 1
                    # Mark in memory too to avoid redundant DB checks
                    self.services.instagram_reels_manager.mark_reel_processed(url, guild_id)
                    logger.info(f"Skipping already-processed reel (database): {url}")
                    continue

                # Mark as processing
                self.services.instagram_reels_manager.mark_reel_processed(url, guild_id)

                # Process the reel
                try:
                    # Update status
                    await status_msg.edit(
                        content=f"🔄 Processing reel {reels_processed + 1}/{max_reels}...\n"
                        f"Messages checked: {messages_checked} | Found: {reels_found} | Skipped: {reels_skipped}",
                    )

                    # Run full analysis via manager
                    data = await self.services.instagram_reels_manager.run_analysis_workflow(
                        url, job_id_suffix=f"past_{message.id}"
                    )

                    # Extract the summary
                    summary = data.get("summary", "No summary generated")

                    # Store in vectordb
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

                        reels_processed += 1
                        logger.info(f"Successfully processed and stored reel: {url}")

                    except Exception as storage_error:
                        logger.error(
                            f"Failed to store reel embeddings for {url}: {storage_error}",
                            exc_info=True,
                        )
                        # Still count as processed even if storage fails
                        reels_processed += 1

                except Exception as e:
                    logger.error(f"Error processing reel {url}: {e}", exc_info=True)
                    # Continue to next reel
                    continue

                # Check if we've hit our target
                if reels_processed >= max_reels:
                    break

            # Final status update
            await status_msg.edit(
                content=f"✅ **Scan Complete**\n"
                f"Messages checked: {messages_checked}\n"
                f"Reels found: {reels_found}\n"
                f"Reels processed: {reels_processed}\n"
                f"Reels skipped (already processed): {reels_skipped}",
            )

        except Exception as e:
            logger.error(f"Error during reel-process-past: {e}", exc_info=True)
            await status_msg.edit(
                content=f"❌ Error during scan: {str(e)}\n"
                f"Messages checked: {messages_checked}\n"
                f"Reels processed: {reels_processed}",
            )

    # Message handler logic
    async def filter_message(self, message: discord.Message) -> bool:
        # Check if the specific channel or thread is being monitored
        channel_id = message.channel.id

        # Check if channel is monitored
        if not self.services.instagram_reels_manager.is_channel_monitored(channel_id):
            return False

        if message.author.bot:
            return False

        # Only process if it has a reel URL
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
