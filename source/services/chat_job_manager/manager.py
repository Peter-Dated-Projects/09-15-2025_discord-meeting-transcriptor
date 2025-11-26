"""
Chat Job Manager Service.

This service manages a queue of chat jobs that are created when users interact
with the bot. It uses an event-based job queue that:
- Processes chat requests with AI responses
- Handles message queuing while AI is thinking
- Manages conversation state (idle, thinking, processing_queue)
- Tracks job status in the SQL database
- Saves conversation data after each response cycle
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from source.server.sql_models import JobsStatus, JobsType
from source.services.common.job import Job, JobQueue
from source.services.conversation_manager.in_memory_cache import (
    Conversation,
    ConversationStatus,
    Message,
    MessageType,
)
from source.services.manager import Manager
from source.utils import generate_16_char_uuid, get_current_timestamp_est
from datetime import datetime

# Maximum number of user messages to batch together
MAX_MESSAGE_BATCH_SIZE = 5


@dataclass
class QueuedUserMessage:
    """
    Represents a user message that's queued while AI is thinking.

    Attributes:
        user_id: Discord user ID of the message sender
        content: Message content
        timestamp: When the message was received
    """

    user_id: str
    content: str
    timestamp: datetime


@dataclass
class ChatJob(Job):
    """
    A job representing a chatbot conversation request.

    This job handles:
    - Initial user query processing
    - AI response generation
    - Message queuing while AI is thinking
    - Conversation state management
    - Iterative message processing from queue

    Attributes:
        thread_id: Discord thread ID where conversation is happening
        conversation_id: SQL conversation ID
        initial_message: Initial user message to process
        initial_user_id: Discord user ID of initial requester
        services: Reference to ServicesManager for accessing services
        message_queue: Queue of user messages received while AI is processing
    """

    thread_id: str = ""
    conversation_id: str = ""
    initial_message: str = ""
    initial_user_id: str = ""
    services: ServicesManager = None  # type: ignore
    message_queue: deque[QueuedUserMessage] = field(default_factory=deque)

    # -------------------------------------------------------------- #
    # Job Execution
    # -------------------------------------------------------------- #

    async def execute(self) -> None:
        """
        Execute the chat job.

        This will:
        1. Process the initial user message
        2. Generate AI response with GPU lock
        3. Send response to Discord
        4. Process any queued messages
        5. Update conversation status
        """
        if not self.services:
            raise RuntimeError("ServicesManager not provided to ChatJob")

        await self.services.logging_service.info(f"Starting chat job for thread {self.thread_id}")

        try:
            # Process initial message (user attribution will be added when building LLM messages)
            await self._process_user_message(self.initial_message, self.initial_user_id)

            # Process queue until empty
            while len(self.message_queue) > 0:
                await self._process_message_queue()

            # Mark conversation as idle
            await self._set_conversation_status(ConversationStatus.IDLE)

            await self.services.logging_service.info(
                f"Completed chat job for thread {self.thread_id}"
            )

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to process chat job for thread {self.thread_id}: {str(e)}"
            )
            # Mark conversation as idle even on error
            await self._set_conversation_status(ConversationStatus.IDLE)
            raise

    # -------------------------------------------------------------- #
    # Message Processing Methods
    # -------------------------------------------------------------- #

    async def _process_user_message(self, message_content: str, user_id: str) -> None:
        """
        Process a user message and generate AI response.

        Args:
            message_content: The user's message content (may be pre-formatted with user labels)
            user_id: Discord user ID of the message sender
        """
        # Get conversation from in-memory cache
        conversation = self.services.conversation_manager.get_conversation(self.thread_id)

        if not conversation:
            await self.services.logging_service.error(
                f"Conversation not found for thread {self.thread_id}"
            )
            return

        # Add user message to conversation
        user_message = Message(
            created_at=datetime.now(),
            message_type=MessageType.CHAT,
            message_content=message_content,
            requester=user_id,
        )
        conversation.add_message(user_message)

        # Save conversation (user message added)
        await conversation.save_conversation()

        # Update conversation status to thinking
        await self._set_conversation_status(ConversationStatus.THINKING)

        # Build message history for LLM
        messages = await self._build_llm_messages(conversation)

        # Generate AI response WITH GPU LOCK
        try:
            async with self.services.gpu_resource_manager.acquire_lock(
                job_type="chatbot",
                job_id=self.job_id,
                metadata={
                    "thread_id": self.thread_id,
                    "conversation_id": self.conversation_id,
                    "user_id": user_id,
                },
            ):
                # GPU is now locked - perform LLM inference
                response = await self._call_llm(messages)

                await self.services.logging_service.info(
                    f"Generated AI response for thread {self.thread_id}"
                )

            # GPU lock automatically released here

        except Exception as e:
            await self.services.logging_service.error(f"Failed to generate AI response: {str(e)}")
            raise

        # Parse and send AI response
        await self._parse_and_send_response(response, conversation)

        # Save conversation (AI response added)
        await conversation.save_conversation()

        # Update conversation timestamp in SQL
        await self.services.conversations_sql_manager.update_conversation_timestamp(
            self.conversation_id
        )

    async def _process_message_queue(self) -> None:
        """
        Process queued messages by batching up to MAX_MESSAGE_BATCH_SIZE messages.

        This will:
        1. Collect up to 5 messages from any users
        2. Save individual messages to conversation history (without formatting)
        3. Build formatted prompt with user identification for LLM
        4. Generate and send AI response
        """
        if len(self.message_queue) == 0:
            return

        # Update status to processing queue
        await self._set_conversation_status(ConversationStatus.PROCESSING_QUEUE)

        # Collect up to MAX_MESSAGE_BATCH_SIZE messages from the queue
        messages_to_process = []
        while len(self.message_queue) > 0 and len(messages_to_process) < MAX_MESSAGE_BATCH_SIZE:
            messages_to_process.append(self.message_queue.popleft())

        # Get conversation
        conversation = self.services.conversation_manager.get_conversation(self.thread_id)

        if not conversation:
            await self.services.logging_service.error(
                f"Conversation not found for thread {self.thread_id}"
            )
            return

        # Add all individual messages to conversation (original content, no formatting)
        for msg in messages_to_process:
            user_message = Message(
                created_at=msg.timestamp,
                message_type=MessageType.CHAT,
                message_content=msg.content,
                requester=msg.user_id,
            )
            conversation.add_message(user_message)

        # Save conversation (queued messages added)
        await conversation.save_conversation()

        # Update conversation status to thinking
        await self._set_conversation_status(ConversationStatus.THINKING)

        await self.services.logging_service.info(
            f"Processing batch of {len(messages_to_process)} messages in thread {self.thread_id}"
        )

        # Build message history for LLM (with user attribution)
        messages = await self._build_llm_messages(conversation)

        # Generate AI response WITH GPU LOCK
        try:
            async with self.services.gpu_resource_manager.acquire_lock(
                job_type="chatbot",
                job_id=self.job_id,
                metadata={
                    "thread_id": self.thread_id,
                    "conversation_id": self.conversation_id,
                    "user_id": messages_to_process[-1].user_id,
                },
            ):
                # GPU is now locked - perform LLM inference
                response = await self._call_llm(messages)

                await self.services.logging_service.info(
                    f"Generated AI response for thread {self.thread_id}"
                )

            # GPU lock automatically released here

        except Exception as e:
            await self.services.logging_service.error(f"Failed to generate AI response: {str(e)}")
            raise

        # Parse and send AI response
        await self._parse_and_send_response(response, conversation)

        # Save conversation (AI response added)
        await conversation.save_conversation()

        # Update conversation timestamp in SQL
        await self.services.conversations_sql_manager.update_conversation_timestamp(
            self.conversation_id
        )

    # -------------------------------------------------------------- #
    # LLM Interaction Methods
    # -------------------------------------------------------------- #

    async def _build_llm_messages(self, conversation: Conversation) -> list[dict[str, str]]:
        """
        Build message history for LLM from conversation.

        Adds user attribution to all user messages to clearly identify speakers.

        Args:
            conversation: The conversation object

        Returns:
            List of message dicts for LLM with user attribution
        """
        messages = []

        # Add system prompt
        system_prompt = (
            "You are Echo, a helpful and knowledgeable assistant. "
            "You have access to conversation history and should provide "
            "thoughtful, contextual responses. You currently have no tools available. "
            "When thinking through complex requests, share your thought process. "
            "Be concise yet thorough in your responses. "
            "In group conversations, users are identified by their display names before their messages."
        )
        messages.append({"role": "system", "content": system_prompt})

        # Collect all unique user IDs from conversation history
        user_ids = set()
        for msg in conversation.history:
            if msg.message_type == MessageType.CHAT and msg.requester:
                user_ids.add(msg.requester)

        # Get display names for all users (batch fetch)
        user_display_names = {}
        if user_ids:
            user_display_names = await self._get_user_display_names(list(user_ids))

        # Add conversation history with user attribution
        for msg in conversation.history:
            if msg.message_type == MessageType.CHAT:
                # Determine role based on requester
                if msg.requester:
                    role = "user"
                    # Add user attribution to the message content
                    user_display = user_display_names.get(msg.requester, f"User {msg.requester}")
                    content = f"{user_display}: {msg.message_content}"
                else:
                    role = "assistant"
                    content = msg.message_content

                messages.append({"role": role, "content": content})

            elif msg.message_type == MessageType.THINKING:
                # Thinking messages are assistant's internal thoughts
                # We can optionally include them or skip them
                # For now, skip to keep history cleaner
                pass

        return messages

    async def _call_llm(self, messages: list[dict[str, str]]) -> dict:
        """
        Call the LLM with messages and return response.

        Args:
            messages: List of message dicts for LLM

        Returns:
            Response dict from Ollama
        """
        response = await self.services.ollama_request_manager.query(
            model=None,  # Use default model
            messages=messages,
            temperature=0.7,
            stream=False,
        )

        return response

    async def _parse_and_send_response(self, response: dict, conversation: Conversation) -> None:
        """
        Parse LLM response and send to Discord.

        The response may contain both thinking and chat content.
        We separate them and send appropriately formatted messages.

        Args:
            response: Response from LLM
            conversation: Conversation object
        """
        # Extract content from response
        content = response.content if hasattr(response, "content") else ""

        if not content:
            await self.services.logging_service.warning(
                f"Empty response from LLM for thread {self.thread_id}"
            )
            return

        # For now, treat all content as chat response
        # In the future, we can implement thinking/chat separation logic
        # by parsing special markers or using structured output

        # Check if content has thinking pattern (optional enhancement)
        thinking_content, chat_content = self._separate_thinking_and_chat(content)

        # Get Discord thread
        thread = await self._get_discord_thread()

        if not thread:
            await self.services.logging_service.error(
                f"Could not find Discord thread {self.thread_id}"
            )
            return

        # Send thinking message if present (italicized)
        if thinking_content:
            thinking_message = Message(
                created_at=datetime.now(),
                message_type=MessageType.THINKING,
                message_content=thinking_content,
                requester=None,
            )
            conversation.add_message(thinking_message)

            # Send to Discord (italicized)
            await thread.send(f"*{thinking_content}*")

        # Send chat message (normal)
        if chat_content:
            chat_message = Message(
                created_at=datetime.now(),
                message_type=MessageType.CHAT,
                message_content=chat_content,
                requester=None,
            )
            conversation.add_message(chat_message)

            # Send to Discord (normal)
            await thread.send(chat_content)

    def _separate_thinking_and_chat(self, content: str) -> tuple[str, str]:
        """
        Separate thinking and chat content from LLM response.

        For now, this is a simple implementation that treats all content as chat.
        In the future, we can implement pattern matching for thinking tags.

        Args:
            content: Full content from LLM

        Returns:
            Tuple of (thinking_content, chat_content)
        """
        # Simple implementation: no thinking separation yet
        # All content is treated as chat
        thinking_content = ""
        chat_content = content

        # Future enhancement: Parse for <thinking> tags or similar patterns
        # if "<thinking>" in content:
        #     # Extract thinking section
        #     pass

        return thinking_content, chat_content

    async def _get_user_display_names(self, user_ids: list[str]) -> dict[str, str]:
        """
        Get display names for Discord user IDs.

        Args:
            user_ids: List of Discord user IDs

        Returns:
            Dictionary mapping user_id to display name
        """
        user_names = {}

        try:
            # Get Discord thread to access guild
            thread = await self._get_discord_thread()

            if not thread or not thread.guild:
                # Fallback to user IDs if we can't get the thread/guild
                return {user_id: f"User {user_id}" for user_id in user_ids}

            # Fetch member objects for each user
            for user_id in user_ids:
                try:
                    member = await thread.guild.fetch_member(int(user_id))
                    # Use display name (nickname if set, otherwise username)
                    user_names[user_id] = member.display_name
                except Exception as e:
                    # If we can't fetch a member, use a fallback
                    await self.services.logging_service.debug(
                        f"Could not fetch member {user_id}: {e}"
                    )
                    user_names[user_id] = f"User {user_id}"

        except Exception as e:
            await self.services.logging_service.error(f"Failed to get user display names: {e}")
            # Fallback to user IDs
            user_names = {user_id: f"User {user_id}" for user_id in user_ids}

        return user_names

    async def _get_discord_thread(self):
        """
        Get Discord thread object from thread_id.

        Returns:
            Discord thread object or None if not found
        """
        try:
            # Access bot from context
            bot = self.services.context.bot

            # Fetch thread/channel
            thread = bot.get_channel(int(self.thread_id))

            if not thread:
                # Try fetching if not in cache
                thread = await bot.fetch_channel(int(self.thread_id))

            return thread

        except Exception as e:
            await self.services.logging_service.error(
                f"Failed to get Discord thread {self.thread_id}: {str(e)}"
            )
            return None

    # -------------------------------------------------------------- #
    # Conversation Status Methods
    # -------------------------------------------------------------- #

    async def _set_conversation_status(self, status: ConversationStatus) -> None:
        """
        Update conversation status in in-memory cache.

        Args:
            status: New conversation status
        """
        conversation = self.services.conversation_manager.get_conversation(self.thread_id)

        if conversation:
            conversation.status = status
            await self.services.logging_service.debug(
                f"Updated conversation {self.thread_id} status to {status.value}"
            )


# -------------------------------------------------------------- #
# Chat Job Manager Service
# -------------------------------------------------------------- #


class ChatJobManagerService(Manager):
    """
    Manager for chat job processing.

    This manager handles:
    - Creating and queuing chat jobs
    - Managing job queue with event-based processing
    - Tracking job status in SQL
    - Routing messages to appropriate jobs
    """

    def __init__(self, context: Context):
        """
        Initialize the chat job manager.

        Args:
            context: Application context
        """
        super().__init__(context)

        # Job queue
        self._job_queue: JobQueue[ChatJob] = JobQueue()
        self._active_jobs: dict[str, ChatJob] = {}  # thread_id -> ChatJob

    # -------------------------------------------------------------- #
    # Manager Lifecycle
    # -------------------------------------------------------------- #

    async def on_start(self, services: ServicesManager) -> None:
        """Actions to perform on manager start."""
        await super().on_start(services)

        # Set up job queue callbacks
        self._job_queue.on_job_completed = self._on_job_completed
        self._job_queue.on_job_failed = self._on_job_failed

        # Start processing queue
        await self._job_queue.start()

        await self.services.logging_service.info("Chat Job Manager started")

    async def on_close(self) -> None:
        """Actions to perform on manager shutdown."""
        await self._job_queue.stop()
        await self.services.logging_service.info("Chat Job Manager stopped")

    # -------------------------------------------------------------- #
    # Job Creation and Management
    # -------------------------------------------------------------- #

    async def create_and_queue_chat_job(
        self,
        thread_id: str,
        conversation_id: str,
        message: str,
        user_id: str,
    ) -> str:
        """
        Create and queue a new chat job.

        Args:
            thread_id: Discord thread ID
            conversation_id: SQL conversation ID
            message: User message to process
            user_id: Discord user ID

        Returns:
            Job ID of the created job
        """
        job_id = generate_16_char_uuid()

        # Create chat job
        chat_job = ChatJob(
            job_id=job_id,
            thread_id=thread_id,
            conversation_id=conversation_id,
            initial_message=message,
            initial_user_id=user_id,
            services=self.services,
        )

        # Track active job
        self._active_jobs[thread_id] = chat_job

        # Create SQL job entry
        await self._create_job_entry(job_id, thread_id)

        # Add to queue
        await self._job_queue.add_job(chat_job)

        await self.services.logging_service.info(
            f"Created and queued chat job {job_id} for thread {thread_id}"
        )

        return job_id

    async def queue_user_message(self, thread_id: str, message: str, user_id: str) -> bool:
        """
        Queue a user message to an active chat job.

        If the thread has an active job (AI is thinking), the message
        is added to the job's queue. Otherwise, a new job is created.

        Args:
            thread_id: Discord thread ID
            message: User message content
            user_id: Discord user ID

        Returns:
            True if message was queued, False if new job needed
        """
        # Check if there's an active job for this thread
        active_job = self._active_jobs.get(thread_id)

        if active_job:
            # Add message to job's queue
            queued_msg = QueuedUserMessage(
                user_id=user_id, content=message, timestamp=datetime.now()
            )
            active_job.message_queue.append(queued_msg)

            await self.services.logging_service.info(
                f"Queued message from user {user_id} to active job for thread {thread_id}"
            )

            return True

        return False

    # -------------------------------------------------------------- #
    # Job Callbacks
    # -------------------------------------------------------------- #

    async def _on_job_completed(self, job: ChatJob) -> None:
        """
        Callback when a job completes successfully.

        Args:
            job: The completed job
        """
        # Update SQL job status
        await self._update_job_status(job.job_id, JobsStatus.COMPLETED)

        # Remove from active jobs
        if job.thread_id in self._active_jobs:
            del self._active_jobs[job.thread_id]

        await self.services.logging_service.info(f"Chat job {job.job_id} completed")

    async def _on_job_failed(self, job: ChatJob, error: Exception) -> None:
        """
        Callback when a job fails.

        Args:
            job: The failed job
            error: The exception that caused the failure
        """
        # Update SQL job status
        await self._update_job_status(job.job_id, JobsStatus.FAILED, str(error))

        # Remove from active jobs
        if job.thread_id in self._active_jobs:
            del self._active_jobs[job.thread_id]

        await self.services.logging_service.error(f"Chat job {job.job_id} failed: {str(error)}")

    # -------------------------------------------------------------- #
    # SQL Methods
    # -------------------------------------------------------------- #

    async def _create_job_entry(self, job_id: str, thread_id: str) -> None:
        """
        Create a job entry in the SQL database.

        Args:
            job_id: Job identifier
            thread_id: Discord thread ID
        """
        from sqlalchemy import insert

        from source.server.sql_models import JobsModel

        timestamp = get_current_timestamp_est()

        job_data = {
            "id": job_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "status": JobsStatus.PENDING.value,
            "type": JobsType.CHATBOT.value,
            "meta": {"thread_id": thread_id},
        }

        stmt = insert(JobsModel).values(**job_data)
        await self.server.sql_client.execute(stmt)

    async def _update_job_status(
        self, job_id: str, status: JobsStatus, error_message: str | None = None
    ) -> None:
        """
        Update job status in SQL database.

        Args:
            job_id: Job identifier
            status: New job status
            error_message: Optional error message for failed jobs
        """
        from sqlalchemy import update

        from source.server.sql_models import JobsModel

        timestamp = get_current_timestamp_est()

        update_data = {
            "updated_at": timestamp,
            "status": status.value,
        }

        if error_message:
            update_data["meta"] = {"error": error_message}

        stmt = update(JobsModel).where(JobsModel.id == job_id).values(**update_data)
        await self.server.sql_client.execute(stmt)
