import discord
from discord.ext import commands
from datetime import datetime

from source.context import Context


class MeetingsPaginationView(discord.ui.View):
    """Pagination view for the /meetings command."""

    def __init__(
        self,
        ctx: discord.ApplicationContext,
        guild_id: str,
        services_manager,
        current_page: int = 0,
    ):
        super().__init__(timeout=300)  # 5 minute timeout
        self.ctx = ctx
        self.guild_id = guild_id
        self.services = services_manager
        self.current_page = current_page
        self.items_per_page = 10

    async def get_meetings_page(self):
        """Fetch the current page of meetings."""
        offset = self.current_page * self.items_per_page
        meetings = await self.services.sql_recording_service_manager.get_meetings_by_guild(
            guild_id=self.guild_id,
            limit=self.items_per_page,
            offset=offset,
        )
        return meetings

    async def create_embed(self):
        """Create an embed for the current page."""
        meetings = await self.get_meetings_page()

        if not meetings:
            embed = discord.Embed(
                title="📋 Meetings",
                description="No meetings found for this server.",
                color=discord.Color.blue(),
            )
            return embed, False

        embed = discord.Embed(
            title="📋 Meetings",
            description=f"Showing meetings for **{self.ctx.guild.name}**",
            color=discord.Color.blue(),
        )

        for meeting in meetings:
            # Format the date
            started_at = meeting.get("started_at")
            if isinstance(started_at, datetime):
                date_str = discord.utils.format_dt(started_at, style="f")
            else:
                date_str = str(started_at)

            # Get participants and format them as mentions (without pings)
            participants = meeting.get("participants", {})
            participant_list = []

            # Extract user IDs from participants dictionary
            if isinstance(participants, dict):
                for user_ids in participants.values():
                    if isinstance(user_ids, list):
                        participant_list.extend(user_ids)
                    elif isinstance(user_ids, str):
                        participant_list.append(user_ids)

            # Format as mentions without pings
            if participant_list:
                mentions = ", ".join([f"<@{uid}>" for uid in set(participant_list)])
            else:
                mentions = "No participants"

            # Get meeting status
            status = meeting.get("status", "Unknown")
            status_emoji = {
                "SCHEDULED": "⏰",
                "RECORDING": "🔴",
                "PROCESSING": "⚙️",
                "CLEANING": "🧹",
                "COMPLETED": "✅",
            }.get(status, "❓")

            embed.add_field(
                name=f"{status_emoji} Meeting: `{meeting['id']}`",
                value=(
                    f"**Date:** {date_str}\n"
                    f"**Status:** {status}\n"
                    f"**Participants:** {mentions}"
                ),
                inline=False,
            )

        # Add footer with page information
        embed.set_footer(text=f"Page {self.current_page + 1}")

        # Check if there are more pages
        has_more = len(meetings) == self.items_per_page

        return embed, has_more

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary, disabled=True)
    async def previous_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Go to the previous page."""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Only the command user can navigate pages.", ephemeral=True
            )
            return

        await self.services.logging_service.info(
            f"User {interaction.user.id} navigated to previous page (page {self.current_page} -> {max(0, self.current_page - 1)}) in guild {self.guild_id}"
        )
        self.current_page = max(0, self.current_page - 1)
        await self.update_view(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        """Go to the next page."""
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Only the command user can navigate pages.", ephemeral=True
            )
            return

        await self.services.logging_service.info(
            f"User {interaction.user.id} navigated to next page (page {self.current_page} -> {self.current_page + 1}) in guild {self.guild_id}"
        )
        self.current_page += 1
        await self.update_view(interaction)

    async def update_view(self, interaction: discord.Interaction):
        """Update the embed and button states."""
        embed, has_more = await self.create_embed()

        # Update button states
        self.children[0].disabled = self.current_page == 0
        self.children[1].disabled = not has_more

        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        """Disable buttons when the view times out."""
        for child in self.children:
            child.disabled = True
        try:
            await self.ctx.edit(view=self)
        except:
            pass  # Message might have been deleted


class General(commands.Cog):
    """General purpose commands."""

    def __init__(self, context: Context):
        self.context = context
        # Backward compatibility properties
        self.bot = context.bot
        self.server = context.server_manager
        self.services = context.services_manager

    # -------------------------------------------------------------- #
    # Slash Commands
    # -------------------------------------------------------------- #

    @commands.slash_command(name="whoami", description="Display information about the bot")
    async def whoami(self, ctx: discord.ApplicationContext):
        """Display bot information with an embed."""

        # Create embed with bot information
        embed = discord.Embed(
            title=self.bot.user.name,
            description=(
                self.bot.user.bio
                if hasattr(self.bot.user, "bio") and self.bot.user.bio
                else "A Discord bot for meeting transcription"
            ),
            color=discord.Color.blue(),
        )

        # Set the bot's avatar as the embed image
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)

        # Add additional information
        embed.add_field(name="Bot ID", value=self.bot.user.id, inline=True)
        embed.add_field(
            name="Created At",
            value=discord.utils.format_dt(self.bot.user.created_at, style="D"),
            inline=True,
        )

        # Set footer
        embed.set_footer(
            text=f"Requested by {ctx.author.name}",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else None,
        )

        # Send the embed as a response
        await ctx.respond(embed=embed)

    @commands.slash_command(name="meetings", description="List all meetings in this server")
    async def meetings(self, ctx: discord.ApplicationContext):
        """List all meetings in the server with pagination."""
        # Log command invocation
        await self.services.logging_service.info(
            f"User {ctx.author.id} ({ctx.author.name}) requested meetings list for guild {ctx.guild_id} ({ctx.guild.name})"
        )

        # Defer response since this might take a moment
        await ctx.defer()

        # Create pagination view
        view = MeetingsPaginationView(
            ctx=ctx,
            guild_id=str(ctx.guild_id),
            services_manager=self.services,
            current_page=0,
        )

        # Get initial embed
        await self.services.logging_service.info(
            f"Fetching first page of meetings for guild {ctx.guild_id}"
        )
        embed, has_more = await view.create_embed()

        # Update button states
        view.children[0].disabled = True  # Previous button starts disabled
        view.children[1].disabled = not has_more  # Next button disabled if no more pages

        await self.services.logging_service.info(
            f"Sending meetings list to user {ctx.author.id} - has_more: {has_more}"
        )
        # Send the response
        await ctx.followup.send(embed=embed, view=view)

    @commands.slash_command(
        name="info", description="Display detailed information about a specific meeting"
    )
    async def info(
        self,
        ctx: discord.ApplicationContext,
        meeting_id: str = discord.Option(description="The meeting ID to get information about"),
    ):
        """Display detailed information about a specific meeting."""
        # Log command invocation
        await self.services.logging_service.info(
            f"User {ctx.author.id} ({ctx.author.name}) requested info for meeting {meeting_id} in guild {ctx.guild_id}"
        )

        # Defer response since this might take a moment
        await ctx.defer()

        try:
            # Get meeting details
            await self.services.logging_service.info(
                f"Fetching meeting details from database for meeting {meeting_id}"
            )
            meeting = await self.services.sql_recording_service_manager.get_meeting(meeting_id)
            
            await self.services.logging_service.info(
                f"Successfully retrieved meeting {meeting_id} - Status: {meeting.get('status')}"
            )

            # Create embed with meeting information
            embed = discord.Embed(
                title=f"📊 Meeting Information",
                description=f"Details for meeting `{meeting_id}`",
                color=discord.Color.green(),
            )

            # Meeting ID and Status
            status = meeting.get("status", "Unknown")
            status_emoji = {
                "SCHEDULED": "⏰",
                "RECORDING": "🔴",
                "PROCESSING": "⚙️",
                "CLEANING": "🧹",
                "COMPLETED": "✅",
            }.get(status, "❓")

            embed.add_field(
                name="Meeting ID",
                value=f"`{meeting['id']}`",
                inline=True,
            )
            embed.add_field(
                name="Status",
                value=f"{status_emoji} {status}",
                inline=True,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer

            # Dates
            started_at = meeting.get("started_at")
            ended_at = meeting.get("ended_at")

            if isinstance(started_at, datetime):
                start_str = discord.utils.format_dt(started_at, style="F")
            else:
                start_str = str(started_at) if started_at else "N/A"

            if isinstance(ended_at, datetime):
                end_str = discord.utils.format_dt(ended_at, style="F")
            else:
                end_str = str(ended_at) if ended_at else "N/A"

            embed.add_field(
                name="🗓️ Started At",
                value=start_str,
                inline=False,
            )
            embed.add_field(
                name="🏁 Ended At",
                value=end_str,
                inline=False,
            )

            # Requested by
            requested_by = meeting.get("requested_by")
            if requested_by:
                embed.add_field(
                    name="👤 Requested By",
                    value=f"<@{requested_by}>",
                    inline=False,
                )

            # Participants
            participants = meeting.get("participants", {})
            participant_list = []

            if isinstance(participants, dict):
                for user_ids in participants.values():
                    if isinstance(user_ids, list):
                        participant_list.extend(user_ids)
                    elif isinstance(user_ids, str):
                        participant_list.append(user_ids)

            if participant_list:
                mentions = ", ".join([f"<@{uid}>" for uid in set(participant_list)])
                embed.add_field(
                    name="👥 Participants",
                    value=mentions,
                    inline=False,
                )

            # Recording IDs
            recording_files = meeting.get("recording_files", {})
            if recording_files and isinstance(recording_files, dict):
                recording_ids = []
                for user_id, rec_ids in recording_files.items():
                    if isinstance(rec_ids, list):
                        recording_ids.extend(rec_ids)
                    elif isinstance(rec_ids, str):
                        recording_ids.append(rec_ids)

                if recording_ids:
                    rec_str = ", ".join([f"`{rid}`" for rid in recording_ids[:5]])
                    if len(recording_ids) > 5:
                        rec_str += f" ... and {len(recording_ids) - 5} more"
                    embed.add_field(
                        name=f"🎙️ Recording IDs ({len(recording_ids)})",
                        value=rec_str,
                        inline=False,
                    )

            # Transcript IDs
            transcript_ids = meeting.get("transcript_ids", {})
            if transcript_ids and isinstance(transcript_ids, dict):
                trans_ids = []
                for user_id, t_ids in transcript_ids.items():
                    if isinstance(t_ids, list):
                        trans_ids.extend(t_ids)
                    elif isinstance(t_ids, str):
                        trans_ids.append(t_ids)

                if trans_ids:
                    trans_str = ", ".join([f"`{tid}`" for tid in trans_ids[:5]])
                    if len(trans_ids) > 5:
                        trans_str += f" ... and {len(trans_ids) - 5} more"
                    embed.add_field(
                        name=f"📝 Transcript IDs ({len(trans_ids)})",
                        value=trans_str,
                        inline=False,
                    )

            # Try to get compiled transcript and summary
            await self.services.logging_service.info(
                f"Attempting to fetch compiled transcript for meeting {meeting_id}"
            )
            try:
                compiled = await self.services.sql_recording_service_manager.get_compiled_transcript_for_meeting(
                    meeting_id
                )
                if compiled:
                    await self.services.logging_service.info(
                        f"Found compiled transcript {compiled.get('id')} for meeting {meeting_id}"
                    )
                    # Add compiled transcript ID
                    embed.add_field(
                        name="📄 Compiled Transcript ID",
                        value=f"`{compiled.get('id')}`",
                        inline=False,
                    )

                    # Load the compiled transcript using the file service manager
                    # which knows the proper base path for transcript storage
                    import json
                    import os
                    import aiofiles

                    # The transcript_filename from the DB contains the full path or relative path
                    transcript_file = compiled.get("transcript_filename")
                    await self.services.logging_service.info(
                        f"Compiled transcript file path from DB: {transcript_file}"
                    )
                    
                    # Check if it's a relative path and build full path using the service manager
                    if transcript_file and not os.path.isabs(transcript_file):
                        # Build full path using transcription_file_service_manager's base path
                        base_path = self.services.transcription_file_service_manager.transcription_storage_path
                        transcript_file = os.path.join(base_path, "compilations", "storage", os.path.basename(transcript_file))
                        await self.services.logging_service.info(
                            f"Built full transcript file path: {transcript_file}"
                        )
                    
                    if transcript_file and os.path.exists(transcript_file):
                        await self.services.logging_service.info(
                            f"Reading compiled transcript file for meeting {meeting_id}"
                        )
                        try:
                            # Use aiofiles for async file reading
                            async with aiofiles.open(transcript_file, mode="r", encoding="utf-8") as f:
                                content = await f.read()
                                transcript_data = json.loads(content)
                                summary = transcript_data.get("summary")
                                
                                if summary:
                                    await self.services.logging_service.info(
                                        f"Found summary for meeting {meeting_id} (length: {len(summary)} chars)"
                                    )
                                    
                                    # Store summary for later - we'll send it in separate messages if too long
                                    # to avoid exceeding Discord's 6000 char embed limit
                                    meeting["_summary"] = summary
                                    
                                    # Add a note that summary will be shown below
                                    embed.add_field(
                                        name="📋 Meeting Summary",
                                        value="*See detailed summary below*" if len(summary) > 1000 else summary[:1000],
                                        inline=False,
                                    )
                                else:
                                    # Summary not yet generated
                                    await self.services.logging_service.info(
                                        f"No summary found in compiled transcript for meeting {meeting_id} - summarization job may not have completed yet"
                                    )
                                    embed.add_field(
                                        name="📋 Meeting Summary",
                                        value="*Summary not yet generated. The summarization job may still be processing.*",
                                        inline=False,
                                    )
                        except json.JSONDecodeError as e:
                            await self.services.logging_service.warning(
                                f"Failed to parse compiled transcript JSON for meeting {meeting_id}: {str(e)}"
                            )
                            embed.add_field(
                                name="📋 Meeting Summary",
                                value="*Error: Compiled transcript file is malformed.*",
                                inline=False,
                            )
                        except Exception as e:
                            await self.services.logging_service.warning(
                                f"Error reading compiled transcript file for meeting {meeting_id}: {str(e)}"
                            )
                            embed.add_field(
                                name="📋 Meeting Summary",
                                value="*Error reading compiled transcript file.*",
                                inline=False,
                            )
                    else:
                        # Compiled transcript exists in DB but file not found
                        await self.services.logging_service.warning(
                            f"Compiled transcript file not found on disk for meeting {meeting_id}: {transcript_file}"
                        )
                        embed.add_field(
                            name="📋 Meeting Summary",
                            value="*Compiled transcript file not found on disk.*",
                            inline=False,
                        )
                else:
                    # No compiled transcript yet
                    await self.services.logging_service.info(
                        f"No compiled transcript found for meeting {meeting_id} - transcription may still be in progress"
                    )
                    embed.add_field(
                        name="📋 Meeting Summary",
                        value="*Compiled transcript not yet available. Transcription may still be in progress.*",
                        inline=False,
                    )
            except Exception as e:
                # Log but don't fail the entire command
                await self.services.logging_service.error(
                    f"Unexpected error fetching compiled transcript for meeting {meeting_id}: {str(e)}"
                )
                embed.add_field(    
                    name="📋 Meeting Summary",
                    value="*Unable to retrieve summary information.*",
                    inline=False,
                )

            # Set footer
            embed.set_footer(
                text=f"Requested by {ctx.author.name}",
                icon_url=ctx.author.avatar.url if ctx.author.avatar else None,
            )

            await self.services.logging_service.info(
                f"Successfully sent meeting info response for meeting {meeting_id} to user {ctx.author.id}"
            )
            await ctx.followup.send(embed=embed)

            # Send summary in separate messages if it's long
            summary = meeting.get("_summary")
            if summary and len(summary) > 1000:
                await self.services.logging_service.info(
                    f"Sending summary in separate messages (length: {len(summary)} chars)"
                )
                
                # Split summary into chunks of 1900 chars (Discord message limit is 2000)
                chunk_size = 1900
                summary_chunks = []
                
                for i in range(0, len(summary), chunk_size):
                    chunk = summary[i:i + chunk_size]
                    summary_chunks.append(chunk)
                
                await self.services.logging_service.info(
                    f"Split summary into {len(summary_chunks)} message(s)"
                )
                
                # Send each chunk as a separate message
                for idx, chunk in enumerate(summary_chunks, start=1):
                    summary_embed = discord.Embed(
                        title=f"📋 Meeting Summary - Part {idx}/{len(summary_chunks)}",
                        description=chunk,
                        color=discord.Color.blue(),
                    )
                    summary_embed.set_footer(text=f"Meeting ID: {meeting_id}")
                    await ctx.followup.send(embed=summary_embed)
                
                await self.services.logging_service.info(
                    f"Successfully sent {len(summary_chunks)} summary message(s) for meeting {meeting_id}"
                )

        except ValueError as e:
            # Meeting not found or invalid ID
            await self.services.logging_service.warning(
                f"Meeting {meeting_id} not found or invalid ID - requested by user {ctx.author.id}: {str(e)}"
            )
            embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                color=discord.Color.red(),
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            # Other errors
            await self.services.logging_service.error(
                f"Unexpected error in /info command for meeting {meeting_id} by user {ctx.author.id}: {str(e)}"
            )
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while fetching meeting information: {str(e)}",
                color=discord.Color.red(),
            )
            await ctx.followup.send(embed=embed, ephemeral=True)

    @commands.slash_command(
        name="deepinfo",
        description="Deep dive into a meeting's processing stages with full verification",
    )
    async def deepinfo(
        self,
        ctx: discord.ApplicationContext,
        meeting_id: str = discord.Option(description="The meeting ID to get deep information about"),
    ):
        """Display comprehensive information about a meeting including all processing stages."""
        # Log command invocation
        await self.services.logging_service.info(
            f"User {ctx.author.id} ({ctx.author.name}) requested deepinfo for meeting {meeting_id} in guild {ctx.guild_id}"
        )

        # Defer response since this will take some time
        await ctx.defer()

        try:
            # ============================================
            # 1. Get basic meeting details (same as /info)
            # ============================================
            await self.services.logging_service.info(
                f"[DEEPINFO] Fetching meeting details from database for meeting {meeting_id}"
            )
            meeting = await self.services.sql_recording_service_manager.get_meeting(meeting_id)

            await self.services.logging_service.info(
                f"[DEEPINFO] Successfully retrieved meeting {meeting_id} - Status: {meeting.get('status')}"
            )

            # Create embed with meeting information
            embed = discord.Embed(
                title=f"🔍 Deep Meeting Analysis",
                description=f"Comprehensive processing information for meeting `{meeting_id}`",
                color=discord.Color.blue(),
            )

            # Meeting ID and Status
            status = meeting.get("status", "Unknown")
            status_emoji = {
                "SCHEDULED": "⏰",
                "RECORDING": "🔴",
                "PROCESSING": "⚙️",
                "CLEANING": "🧹",
                "COMPLETED": "✅",
                "TRANSCRIBING": "📝",
            }.get(status, "❓")

            embed.add_field(
                name="Meeting ID",
                value=f"`{meeting['id']}`",
                inline=True,
            )
            embed.add_field(
                name="Status",
                value=f"{status_emoji} {status}",
                inline=True,
            )
            embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer

            # Dates
            started_at = meeting.get("started_at")
            ended_at = meeting.get("ended_at")

            if isinstance(started_at, datetime):
                start_str = discord.utils.format_dt(started_at, style="F")
            else:
                start_str = str(started_at) if started_at else "N/A"

            if isinstance(ended_at, datetime):
                end_str = discord.utils.format_dt(ended_at, style="F")
            else:
                end_str = str(ended_at) if ended_at else "N/A"

            embed.add_field(
                name="🗓️ Started At",
                value=start_str,
                inline=False,
            )
            embed.add_field(
                name="🏁 Ended At",
                value=end_str,
                inline=False,
            )

            # Requested by
            requested_by = meeting.get("requested_by")
            if requested_by:
                embed.add_field(
                    name="👤 Requested By",
                    value=f"<@{requested_by}>",
                    inline=False,
                )

            # Participants
            participants = meeting.get("participants", {})
            participant_list = []

            if isinstance(participants, dict):
                for user_ids in participants.values():
                    if isinstance(user_ids, list):
                        participant_list.extend(user_ids)
                    elif isinstance(user_ids, str):
                        participant_list.append(user_ids)

            if participant_list:
                mentions = ", ".join([f"<@{uid}>" for uid in set(participant_list)])
                embed.add_field(
                    name="👥 Participants",
                    value=mentions,
                    inline=False,
                )

            # Add footer note about thread
            embed.set_footer(text="📋 Detailed analysis will be posted in the thread below...")

            # Send initial embed
            webhook_message = await ctx.followup.send(embed=embed)
            
            # Fetch the actual message from the channel to get guild info
            # WebhookMessage doesn't have guild info, so we need to fetch it
            initial_message = await ctx.channel.fetch_message(webhook_message.id)
            
            # Create a thread for detailed analysis
            thread = await initial_message.create_thread(
                name=f"Deep Analysis: {meeting_id}",
                auto_archive_duration=1440  # 24 hours
            )
            
            await self.services.logging_service.info(
                f"[DEEPINFO] Created thread {thread.id} for meeting {meeting_id} analysis"
            )

            # ============================================
            # 2. Verify and display recording data
            # ============================================
            await self.services.logging_service.info(
                f"[DEEPINFO] Fetching recording data for meeting {meeting_id}"
            )

            # Get temp recordings
            temp_recordings = await self.services.sql_recording_service_manager.get_temp_recordings_for_meeting(
                meeting_id
            )

            # Get persistent recordings
            persistent_recordings = await self.services.sql_recording_service_manager.get_persistent_recordings_for_meeting(
                meeting_id
            )

            # Create recordings embed
            recordings_embed = discord.Embed(
                title="🎙️ Recording Data Verification",
                description=f"Recording stages for meeting `{meeting_id}`",
                color=discord.Color.green(),
            )

            # Temp recordings info
            if temp_recordings:
                temp_info = f"**Count:** {len(temp_recordings)} temporary recording(s)\n"
                temp_info += "**Details:**\n"

                # Group by user
                temp_by_user = {}
                for rec in temp_recordings:
                    user_id = rec.get("user_id")
                    if user_id not in temp_by_user:
                        temp_by_user[user_id] = []
                    temp_by_user[user_id].append(rec)

                for user_id, recs in temp_by_user.items():
                    temp_info += f"  • <@{user_id}>: {len(recs)} chunk(s)\n"
                    for rec in recs[:3]:  # Show first 3 chunks
                        temp_info += f"    - ID: `{rec.get('id')}`, Status: `{rec.get('transcode_status')}`\n"
                    if len(recs) > 3:
                        temp_info += f"    - ... and {len(recs) - 3} more\n"

                recordings_embed.add_field(
                    name="📦 Temporary Recordings",
                    value=temp_info[:1024],  # Discord field limit
                    inline=False,
                )
            else:
                recordings_embed.add_field(
                    name="📦 Temporary Recordings",
                    value="*No temporary recordings found (may have been cleaned up)*",
                    inline=False,
                )

            # Persistent recordings info
            if persistent_recordings:
                persist_info = f"**Count:** {len(persistent_recordings)} persistent recording(s)\n"
                persist_info += "**Details:**\n"

                for rec in persistent_recordings:
                    user_id = rec.get("user_id")
                    duration_ms = rec.get("duration_in_ms", 0)
                    duration_sec = duration_ms / 1000 if duration_ms else 0
                    persist_info += f"  • <@{user_id}>:\n"
                    persist_info += f"    - ID: `{rec.get('id')}`\n"
                    persist_info += f"    - Duration: {duration_sec:.2f}s\n"
                    persist_info += f"    - Filename: `{rec.get('filename', 'N/A')}`\n"
                    persist_info += f"    - SHA256: `{rec.get('sha256', 'N/A')[:16]}...`\n"

                recordings_embed.add_field(
                    name="💾 Persistent Recordings",
                    value=persist_info[:1024],  # Discord field limit
                    inline=False,
                )
            else:
                recordings_embed.add_field(
                    name="💾 Persistent Recordings",
                    value="*No persistent recordings found*",
                    inline=False,
                )

            await thread.send(embed=recordings_embed)

            # ============================================
            # 3. Verify and display transcription data
            # ============================================
            await self.services.logging_service.info(
                f"[DEEPINFO] Fetching transcription data for meeting {meeting_id}"
            )

            # Get user transcripts
            user_transcripts = await self.services.transcription_file_service_manager.get_transcriptions_by_meeting(
                meeting_id
            )

            # Create transcripts embed
            transcripts_embed = discord.Embed(
                title="📝 Transcription Data Verification",
                description=f"Transcription stages for meeting `{meeting_id}`",
                color=discord.Color.purple(),
            )

            if user_transcripts:
                trans_info = f"**Count:** {len(user_transcripts)} user transcript(s)\n"
                trans_info += "**Details:**\n"

                for trans in user_transcripts:
                    user_id = trans.get("user_id")
                    trans_info += f"  • <@{user_id}>:\n"
                    trans_info += f"    - ID: `{trans.get('id')}`\n"
                    trans_info += f"    - Filename: `{trans.get('filename', 'N/A')}`\n"
                    trans_info += f"    - SHA256: `{trans.get('sha256', 'N/A')[:16]}...`\n"
                    trans_info += f"    - Created: {trans.get('created_at', 'N/A')}\n"

                transcripts_embed.add_field(
                    name="📄 User Transcripts",
                    value=trans_info[:1024],  # Discord field limit
                    inline=False,
                )
            else:
                transcripts_embed.add_field(
                    name="📄 User Transcripts",
                    value="*No user transcripts found (transcription may not have started)*",
                    inline=False,
                )

            # Get compiled transcript
            compiled = await self.services.sql_recording_service_manager.get_compiled_transcript_for_meeting(
                meeting_id
            )

            if compiled:
                compiled_info = f"**ID:** `{compiled.get('id')}`\n"
                compiled_info += f"**Filename:** `{compiled.get('transcript_filename', 'N/A')}`\n"
                compiled_info += f"**SHA256:** `{compiled.get('sha256', 'N/A')[:16]}...`\n"
                compiled_info += f"**Created:** {compiled.get('created_at', 'N/A')}\n"

                transcripts_embed.add_field(
                    name="📚 Compiled Transcript",
                    value=compiled_info,
                    inline=False,
                )
            else:
                transcripts_embed.add_field(
                    name="📚 Compiled Transcript",
                    value="*No compiled transcript found (compilation may not have started)*",
                    inline=False,
                )

            await thread.send(embed=transcripts_embed)

            # ============================================
            # 4. Display all summary layers
            # ============================================
            await self.services.logging_service.info(
                f"[DEEPINFO] Fetching summary data for meeting {meeting_id}"
            )

            if compiled:
                import json
                import os
                import aiofiles

                # Get the transcript file path
                transcript_file = compiled.get("transcript_filename")

                # Check if it's a relative path and build full path
                if transcript_file and not os.path.isabs(transcript_file):
                    base_path = self.services.transcription_file_service_manager.transcription_storage_path
                    transcript_file = os.path.join(
                        base_path, "compilations", "storage", os.path.basename(transcript_file)
                    )

                if transcript_file and os.path.exists(transcript_file):
                    try:
                        # Read the compiled transcript file
                        async with aiofiles.open(transcript_file, mode="r", encoding="utf-8") as f:
                            content = await f.read()
                            transcript_data = json.loads(content)

                        # Create summary embed
                        summary_embed = discord.Embed(
                            title="📋 Summary Layers",
                            description=f"All summary stages for meeting `{meeting_id}`",
                            color=discord.Color.gold(),
                        )

                        # Check for main summary
                        main_summary = transcript_data.get("summary")
                        if main_summary:
                            summary_preview = main_summary[:500] + "..." if len(main_summary) > 500 else main_summary
                            summary_embed.add_field(
                                name="✨ Main Summary",
                                value=f"**Length:** {len(main_summary)} characters\n**Preview:**\n{summary_preview}",
                                inline=False,
                            )
                        else:
                            summary_embed.add_field(
                                name="✨ Main Summary",
                                value="*Not yet generated*",
                                inline=False,
                            )

                        # Check for summary layers (if they exist)
                        summary_layers = transcript_data.get("summary_layers", {})
                        if summary_layers:
                            layers_info = f"**Found {len(summary_layers)} layer(s):**\n"
                            for layer_name, layer_content in summary_layers.items():
                                if isinstance(layer_content, str):
                                    layers_info += f"  • `{layer_name}`: {len(layer_content)} chars\n"
                                elif isinstance(layer_content, dict):
                                    layers_info += f"  • `{layer_name}`: {len(str(layer_content))} chars (structured)\n"

                            summary_embed.add_field(
                                name="🔄 Summary Layers",
                                value=layers_info[:1024],
                                inline=False,
                            )
                        else:
                            summary_embed.add_field(
                                name="🔄 Summary Layers",
                                value="*No additional summary layers found*",
                                inline=False,
                            )

                        # Check for other relevant fields
                        other_fields = []
                        if "metadata" in transcript_data:
                            other_fields.append("metadata")
                        if "speakers" in transcript_data:
                            other_fields.append("speakers")
                        if "segments" in transcript_data:
                            segments = transcript_data["segments"]
                            if isinstance(segments, list):
                                other_fields.append(f"segments ({len(segments)})")

                        if other_fields:
                            summary_embed.add_field(
                                name="📊 Additional Data",
                                value=", ".join([f"`{field}`" for field in other_fields]),
                                inline=False,
                            )

                        await thread.send(embed=summary_embed)

                        # Send full summary in separate messages if requested
                        if main_summary:
                            await self.services.logging_service.info(
                                f"[DEEPINFO] Sending full summary for meeting {meeting_id}"
                            )

                            # Split summary into chunks of 1900 chars
                            chunk_size = 1900
                            summary_chunks = [
                                main_summary[i:i + chunk_size]
                                for i in range(0, len(main_summary), chunk_size)
                            ]

                            # Send each chunk
                            for idx, chunk in enumerate(summary_chunks, start=1):
                                chunk_embed = discord.Embed(
                                    title=f"📋 Full Summary - Part {idx}/{len(summary_chunks)}",
                                    description=chunk,
                                    color=discord.Color.blue(),
                                )
                                chunk_embed.set_footer(text=f"Meeting ID: {meeting_id}")
                                await thread.send(embed=chunk_embed)

                            # Send summary layers if they exist
                            if summary_layers:
                                for layer_name, layer_content in summary_layers.items():
                                    if isinstance(layer_content, str) and layer_content:
                                        layer_chunks = [
                                            layer_content[i:i + chunk_size]
                                            for i in range(0, len(layer_content), chunk_size)
                                        ]

                                        for idx, chunk in enumerate(layer_chunks, start=1):
                                            layer_embed = discord.Embed(
                                                title=f"📋 {layer_name} - Part {idx}/{len(layer_chunks)}",
                                                description=chunk,
                                                color=discord.Color.teal(),
                                            )
                                            layer_embed.set_footer(text=f"Meeting ID: {meeting_id}")
                                            await thread.send(embed=layer_embed)

                    except json.JSONDecodeError as e:
                        await self.services.logging_service.warning(
                            f"[DEEPINFO] Failed to parse compiled transcript JSON for meeting {meeting_id}: {str(e)}"
                        )
                        error_embed = discord.Embed(
                            title="❌ Summary Error",
                            description="Compiled transcript file is malformed.",
                            color=discord.Color.red(),
                        )
                        await thread.send(embed=error_embed)
                    except Exception as e:
                        await self.services.logging_service.error(
                            f"[DEEPINFO] Error reading compiled transcript file for meeting {meeting_id}: {str(e)}"
                        )
                        error_embed = discord.Embed(
                            title="❌ Summary Error",
                            description="Error reading compiled transcript file.",
                            color=discord.Color.red(),
                        )
                        await thread.send(embed=error_embed)
                else:
                    # File not found
                    await self.services.logging_service.warning(
                        f"[DEEPINFO] Compiled transcript file not found for meeting {meeting_id}: {transcript_file}"
                    )
                    error_embed = discord.Embed(
                        title="⚠️ Summary Not Available",
                        description="Compiled transcript file not found on disk.",
                        color=discord.Color.orange(),
                    )
                    await thread.send(embed=error_embed)
            else:
                # No compiled transcript
                await self.services.logging_service.info(
                    f"[DEEPINFO] No compiled transcript found for meeting {meeting_id}"
                )
                error_embed = discord.Embed(
                    title="⚠️ Summary Not Available",
                    description="Compiled transcript not yet available. Transcription may still be in progress.",
                    color=discord.Color.orange(),
                )
                await thread.send(embed=error_embed)

            # ============================================
            # 5. Final completion message
            # ============================================
            await self.services.logging_service.info(
                f"[DEEPINFO] Successfully completed deep analysis for meeting {meeting_id}"
            )

            final_embed = discord.Embed(
                title="✅ Deep Analysis Complete",
                description=f"All processing stages for meeting `{meeting_id}` have been analyzed.",
                color=discord.Color.green(),
            )
            final_embed.set_footer(
                text=f"Requested by {ctx.author.name}",
                icon_url=ctx.author.avatar.url if ctx.author.avatar else None,
            )
            await thread.send(embed=final_embed)

        except ValueError as e:
            # Meeting not found or invalid ID
            await self.services.logging_service.warning(
                f"[DEEPINFO] Meeting {meeting_id} not found or invalid ID - requested by user {ctx.author.id}: {str(e)}"
            )
            embed = discord.Embed(
                title="❌ Error",
                description=str(e),
                color=discord.Color.red(),
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            # Other errors
            await self.services.logging_service.error(
                f"[DEEPINFO] Unexpected error in /deepinfo command for meeting {meeting_id} by user {ctx.author.id}: {str(e)}"
            )
            import traceback
            await self.services.logging_service.error(
                f"[DEEPINFO] Traceback: {traceback.format_exc()}"
            )
            embed = discord.Embed(
                title="❌ Error",
                description=f"An error occurred while fetching meeting information: {str(e)}",
                color=discord.Color.red(),
            )
            await ctx.followup.send(embed=embed, ephemeral=True)


def setup(context: Context):
    general = General(context)
    context.bot.add_cog(general)
