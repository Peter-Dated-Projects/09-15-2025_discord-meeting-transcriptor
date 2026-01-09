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

        content = message.content
        # Basic check to avoid processing every message
        # Regex for Instagram Reel URL
        url_match = re.search(r"(https?://www\.instagram\.com/(?:reel|p)/[\w-]+)", content)

        if not url_match:
            return

        url = url_match.group(1)
        logger.info(f"Reel detected: {url}")

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

        except Exception as e:
            logger.error(f"Error processing reel: {e}", exc_info=True)
            await status_msg.edit(content=f"❌ Error processing reel: {str(e)}")


def setup(context: Context):
    cog = Reels(context)
    context.bot.add_cog(cog)
    return cog
