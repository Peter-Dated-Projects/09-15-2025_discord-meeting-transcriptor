import logging
import discord
from discord.ext import commands
from source.context import Context

logger = logging.getLogger(__name__)


class Reels(commands.Cog):
    def __init__(self, context: Context):
        self.context = context
        self.bot = context.bot
        self.services = context.services_manager

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

        # Only process if it has a reel URL
        # Basic check, detailed check later
        if "instagram.com" in message.content:
            return True

        return False

    async def handle_message(self, message: discord.Message):
        # "run ministral-3:3b with the verification cool to check if the message has an instragram reel URL"
        import re
        import json
        from datetime import datetime

        content = message.content
        # Basic check to avoid processing every message
        # Regex for Instagram Reel URL
        url_match = re.search(r"(https?://www\.instagram\.com/(?:reel|p)/[\w-]+)", content)

        if not url_match:
            return

        url = url_match.group(1)
        logger.info(f"Reel detected: {url}")

        # Check if this reel has already been processed
        try:
            from source.services.misc.instagram_reels.storage import check_reel_exists

            guild_id = str(message.guild.id) if message.guild else "DM"
            reel_exists = await check_reel_exists(
                services=self.services, reel_url=url, guild_id=guild_id
            )

            if reel_exists:
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

        except Exception as check_error:
            # If check fails, proceed with processing (better to duplicate than skip)
            logger.warning(
                f"Failed to check if reel exists, proceeding with processing: {check_error}"
            )

        status_msg = await message.reply("🔄 Processing Instagram Reel...", mention_author=False)

        try:
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
                    reel_url=url,
                    guild_id=str(message.guild.id) if message.guild else "DM",
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
            await status_msg.edit(content=f"❌ Error processing reel: {str(e)}")


def setup(context: Context):
    cog = Reels(context)
    context.bot.add_cog(cog)
    return cog
