import asyncio
import discord
from discord.ext import commands
from source.context import Context
from source.services.discord.discord_recorder_manager.manager import DiscordRecorderConstants


class Utils(commands.Cog):
    def __init__(self, context: Context):
        self.context = context
        self.bot = context.bot

    @discord.slash_command(
        name="background_clean", description="Run and reset the temp recording cleanup task"
    )
    async def background_clean(self, ctx: discord.ApplicationContext):
        await ctx.defer()

        recorder_manager = self.context.services_manager.discord_recorder_service_manager
        if not recorder_manager:
            await ctx.followup.send("❌ Discord Recorder Manager not available.")
            return

        # 1. Cancel existing task
        if recorder_manager._cleanup_task:
            recorder_manager._cleanup_task.cancel()
            try:
                await recorder_manager._cleanup_task
            except asyncio.CancelledError:
                pass

        response_msg = ""
        # 2. Run cleanup immediately
        try:
            ttl_hours = DiscordRecorderConstants.TEMP_RECORDING_TTL_HOURS
            count = await recorder_manager._cleanup_old_temp_recordings_once(ttl_hours)
            response_msg += f"✅ Cleanup ran successfully. Removed {count} files.\n"
        except Exception as e:
            response_msg += f"❌ Error during cleanup: {e}\n"

        # 3. Restart the background task
        recorder_manager._cleanup_task = asyncio.create_task(
            recorder_manager._cleanup_old_temp_recordings()
        )
        response_msg += "✅ Cleanup task restarted."

        await ctx.followup.send(response_msg)


def setup(context: Context):
    context.bot.add_cog(Utils(context))
