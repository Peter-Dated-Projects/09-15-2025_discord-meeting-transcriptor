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
import os
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context
    from source.services.manager import ServicesManager

from datetime import datetime

from source.server.sql_models import JobsStatus, JobsType
from source.services.common.job import Job, JobQueue
from source.services.chat.conversation_manager.in_memory_cache import (
    Conversation,
    ConversationStatus,
    Message,
    MessageType,
)
from source.services.manager import Manager
from source.utils import generate_16_char_uuid, get_current_timestamp_est
from source.services.chat.chat_job_manager.prompts import CHAT_JOB_SYSTEM_PROMPT

# Maximum number of user messages to batch together
MAX_MESSAGE_BATCH_SIZE = 5

# Get chat model from environment variable
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:12b")


@dataclass
class QueuedUserMessage:
    """
    Represents a user message that's queued while AI is thinking.

    Attributes:
        user_id: Discord user ID of the message sender
        content: Message content
        timestamp: When the message was received
        attachments: List of attachment metadata (URLs, images, files)
    """

    user_id: str
    content: str
    timestamp: datetime
    attachments: list[dict] = field(default_factory=list)


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
    _downloaded_attachments: list[dict] = field(default_factory=list)  # Track for cleanup
    _downloaded_attachments: list[dict] = field(default_factory=list)  # Track for cleanup

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
            # Process initial message if present (user attribution will be added when building LLM messages)
            if self.initial_message:
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

    async def _process_user_message(
        self, message_content: str, user_id: str, attachments: list[dict] | None = None
    ) -> None:
        """
        Process a user message and generate AI response.

        Args:
            message_content: The user's message content (may be pre-formatted with user labels)
            user_id: Discord user ID of the message sender
            attachments: Optional list of attachment metadata
        """
        # Get conversation from in-memory cache
        conversation = self.services.conversation_manager.get_conversation(self.thread_id)

        if not conversation:
            await self.services.logging_service.error(
                f"Conversation not found for thread {self.thread_id}"
            )
            return

        # Download attachments BEFORE adding message to conversation
        # This updates the attachment metadata with local_path
        if attachments:
            attachments = await self._download_attachments_for_processing(attachments)

        # Add user message to conversation with updated attachments
        user_message = Message(
            created_at=datetime.now(),
            message_type=MessageType.CHAT,
            message_content=message_content,
            requester=user_id,
            attachments=attachments,
        )
        conversation.add_message(user_message)

        # Save conversation (user message added with downloaded attachments)
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
            # Check if this is a context length error
            if await self._handle_context_length_error(e):
                return
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

        # Download attachments from all queued messages FIRST
        for msg in messages_to_process:
            if msg.attachments:
                msg.attachments = await self._download_attachments_for_processing(msg.attachments)

        # Add all individual messages to conversation with downloaded attachments
        for msg in messages_to_process:
            user_message = Message(
                created_at=msg.timestamp,
                message_type=MessageType.CHAT,
                message_content=msg.content,
                requester=msg.user_id,
                attachments=msg.attachments if msg.attachments else None,
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
            # Check if this is a context length error
            if await self._handle_context_length_error(e):
                return
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

    async def _build_llm_messages(self, conversation: Conversation) -> list:
        """
        Build message history for LLM from conversation.

        Adds user attribution to all user messages to clearly identify speakers.
        Extracts image paths from attachments for vision model support.

        Args:
            conversation: The conversation object

        Returns:
            List of Message objects for LLM with user attribution and images
        """
        # from source.services.gpu.ollama_request_manager.manager import Message as LLMMessage

        messages = []

        # Add system prompt
        system_prompt = CHAT_JOB_SYSTEM_PROMPT
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

        # Add conversation history with user attribution and timestamps
        for msg in conversation.history:
            if msg.message_type == MessageType.CHAT:
                # Format timestamp as [yyyy-mm-dd_hh-mm]
                timestamp_str = msg.created_at.strftime("[%Y-%m-%d_%H-%M]")

                # Determine role based on requester
                if msg.requester:
                    role = "user"
                    # Add user attribution and timestamp to the message content
                    user_display = user_display_names.get(
                        msg.requester, f"User {msg.requester} <@{msg.requester}>"
                    )
                    content = f"{timestamp_str} {user_display}: {msg.message_content}"

                    # Check if model supports multimodal (vision) capabilities
                    multimodal_enabled = os.getenv("OLLAMA_MULTIMODAL", "false").lower() == "true"

                    # Extract images for vision models
                    image_paths = []
                    image_count = 0  # Track images even if not processing them
                    if msg.attachments:
                        from source.services.chat.chat_job_manager.attachment_utils import (
                            extract_documents_and_images_from_attachments,
                            format_attachments_for_llm,
                        )

                        # Extract text documents and images using Ollama-compatible utilities
                        docs, extracted_image_paths = extract_documents_and_images_from_attachments(
                            msg.attachments
                        )

                        # Count images
                        image_count = len(extracted_image_paths)

                        # Only collect image paths if multimodal is enabled
                        if multimodal_enabled:
                            image_paths = extracted_image_paths
                        else:
                            # Notify the model that images were attached but cannot be viewed
                            if image_count > 0:
                                image_notice = f"\n\n[Note: User attached {image_count} image(s), but you do not have the ability to view images. Please inform the user you cannot process visual content.]"
                                content += image_notice

                        # Add text document content to the message content
                        if docs:
                            from source.services.chat.chat_job_manager.attachment_utils import (
                                build_text_documents_block,
                            )

                            docs_block = build_text_documents_block(docs)
                            content += f"\n\n[Attached Documents]\n{docs_block}"

                        # Only show attachment summary for non-image attachments
                        # Images are passed as base64 in the 'images' field
                        non_image_attachments = [
                            att for att in msg.attachments if att.get("type") != "image"
                        ]
                        if non_image_attachments:
                            attachment_info = format_attachments_for_llm(non_image_attachments)
                            content += attachment_info

                    # Encode images to base64 if present
                    encoded_images = None
                    if image_paths:
                        from source.services.chat.chat_job_manager.attachment_utils import (
                            encode_image_to_base64,
                        )

                        encoded_images = []
                        for path in image_paths:
                            encoded = encode_image_to_base64(path)
                            if encoded:
                                encoded_images.append(encoded)
                        # Only set if we have images
                        encoded_images = encoded_images if encoded_images else None

                        if encoded_images:
                            await self.services.logging_service.debug(
                                f"Encoded {len(encoded_images)} image(s) for vision model"
                            )
                    elif image_count > 0:
                        # Images were present but multimodal is disabled
                        await self.services.logging_service.info(
                            f"Skipped {image_count} image(s) - OLLAMA_MULTIMODAL is disabled"
                        )

                    # Create Message object with optional images
                    msg_dict = {"role": role, "content": content}
                    if encoded_images:
                        msg_dict["images"] = encoded_images
                    messages.append(msg_dict)
                else:
                    # Fallback for old messages without requester but type CHAT
                    role = "assistant"
                    content = msg.message_content
                    messages.append({"role": role, "content": content})

            elif msg.message_type == MessageType.AI_RESPONSE:
                role = "assistant"
                # Assistant messages don't need timestamps (prevents bot from copying format)
                content = msg.message_content
                messages.append({"role": role, "content": content})

            elif msg.message_type == MessageType.TOOL_CALL:
                # Represent tool calls as assistant messages with tool_calls field
                # This helps the model see what it decided to do
                role = "assistant"
                content = ""  # Content is usually empty for tool calls

                # Convert internal tool format to Ollama tool call format
                tool_calls = []
                if msg.tools:
                    for t in msg.tools:
                        tool_calls.append(
                            {
                                "function": {
                                    "name": t.get("name"),
                                    "arguments": t.get("arguments"),
                                },
                                "id": t.get("id", "unknown"),
                            }
                        )

                msg_dict = {"role": role, "content": content}
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                messages.append(msg_dict)

            elif msg.message_type == MessageType.TOOL_CALL_RESPONSE:
                # Represent tool responses as user messages (standard for many chat formats)
                # or as tool messages if the underlying API supports it.
                # For Ollama/generic, we'll use 'tool' role if available, or 'user' with a prefix.

                # Using 'tool' role is safer if the backend supports it, but LLMMessage might not.
                # Let's check LLMMessage definition or usage.
                # Usually 'tool' role is for tool outputs.

                role = "tool"
                content = msg.message_content

                # We assume the message content contains the result
                messages.append({"role": role, "content": content})

            elif msg.message_type == MessageType.THINKING:
                # Thinking messages are assistant's internal thoughts
                # We can optionally include them or skip them
                # For now, skip to keep history cleaner
                pass

        return messages

    async def _call_llm(self, messages: list) -> dict:
        """
        Call the LLM with messages and return response.

        Uses the OLLAMA_CHAT_MODEL environment variable to determine which model to use.
        Sets keep_alive to 1 minute to keep the model in memory briefly after chat requests.
        Automatically retrieves and passes tools from MCP manager if available.

        Args:
            messages: List of Message objects for LLM (may include images field with base64 strings)

        Returns:
            Response dict from Ollama
        """
        # Get tools from MCP manager if available
        tools = None
        if self.services.mcp_manager:
            try:
                tools = await self.services.mcp_manager.get_ollama_tools()
                if tools:
                    await self.services.logging_service.debug(
                        f"Retrieved {len(tools)} tools from MCP manager for LLM request"
                    )
            except Exception as e:
                await self.services.logging_service.warning(
                    f"Failed to retrieve tools from MCP manager: {e}"
                )

        response = await self.services.ollama_request_manager.query(
            model=OLLAMA_CHAT_MODEL,
            messages=messages,
            temperature=0.7,
            stream=False,
            keep_alive="1m",  # Keep model in memory for 1 minute after request
            tools=tools,  # Pass tools to Ollama
        )

        return response

    async def _handle_context_length_error(self, error: Exception) -> bool:
        """
        Check if the error is a context length/message length error and notify user.

        Args:
            error: The exception from the LLM call

        Returns:
            True if this was a context length error and was handled, False otherwise
        """
        error_str = str(error).lower()

        # Common patterns for context length errors from Ollama/LLMs
        context_length_indicators = [
            "context length",
            "context_length",
            "token limit",
            "tokens exceed",
            "maximum context",
            "too many tokens",
            "exceeds the model's maximum",
            "input too long",
            "prompt is too long",
            "message too long",
            "context window",
            "max_tokens",
            "maximum length",
        ]

        is_context_error = any(indicator in error_str for indicator in context_length_indicators)

        if is_context_error:
            try:
                thread = await self._get_discord_thread()
                if thread:
                    await thread.send(
                        "⚠️ **Conversation too long!**\n\n"
                        "This conversation has exceeded the maximum context length for the AI model. "
                        "Please start a new chat thread to continue our conversation.\n\n"
                        "-# *Your previous messages in this thread have been saved.*"
                    )
                    await self.services.logging_service.warning(
                        f"Context length exceeded for thread {self.thread_id}, notified user"
                    )
            except Exception as notify_error:
                await self.services.logging_service.error(
                    f"Failed to notify user about context length error: {notify_error}"
                )

            return True

        return False

    async def _parse_and_send_response(self, response: dict, conversation: Conversation) -> None:
        """
        Parse LLM response and send to Discord.

        The response may contain both thinking and chat content, as well as tool calls.
        We separate them and send appropriately formatted messages.
        If tool calls are present, we execute them, send results back to the LLM,
        and get a final response to send to the user.

        Args:
            response: Response from LLM (OllamaQueryResult)
            conversation: Conversation object
        """
        # Extract content and thinking from response
        content = response.content if hasattr(response, "content") else ""
        thinking_content = (
            response.thinking if hasattr(response, "thinking") and response.thinking else ""
        )
        tool_calls = response.tool_calls if hasattr(response, "tool_calls") else None

        # Handle tool calls if present - execute and get follow-up response
        if tool_calls and self.services.mcp_manager:
            await self.services.logging_service.info(
                f"Processing {len(tool_calls)} tool call(s) from LLM response"
            )

            # Store tool results to send back to LLM
            tool_results = []

            for tool_call in tool_calls:
                try:
                    # Extract tool information
                    tool_name = tool_call["function"]["name"]
                    tool_args = tool_call["function"]["arguments"]
                    tool_id = tool_call.get("id", "unknown")

                    await self.services.logging_service.info(
                        f"Executing tool: {tool_name} with args: {tool_args}"
                    )

                    # Execute the tool
                    tool_result = await self.services.mcp_manager.execute_tool(tool_name, tool_args)

                    await self.services.logging_service.info(
                        f"Tool {tool_name} executed successfully: {tool_result}"
                    )

                    # Add tool call to conversation history
                    tool_call_message = Message(
                        created_at=datetime.now(),
                        message_type=MessageType.TOOL_CALL,
                        message_content=f"Tool: {tool_name}",
                        tools=[{"name": tool_name, "arguments": tool_args, "id": tool_id}],
                        requester=None,
                    )
                    conversation.add_message(tool_call_message)

                    # Format tool result for LLM
                    if isinstance(tool_result, dict):
                        # Check for specific tool result formats
                        if "success" in tool_result:
                            # Discord DM tool format
                            result_str = (
                                f"Tool execution result: {tool_result.get('success', 'unknown')}"
                            )
                            if tool_result.get("error"):
                                result_str += f" - Error: {tool_result['error']}"
                            elif tool_result.get("message_id"):
                                result_str += f" - Message sent (ID: {tool_result['message_id']})"
                        elif "results" in tool_result:
                            # Google Search tool format
                            import json
                            result_str = json.dumps(tool_result["results"], indent=2)
                        elif "content" in tool_result and "url" in tool_result:
                            # Read Webpage tool format
                            result_str = f"Content from {tool_result['url']} (Page {tool_result.get('current_page', 1)}/{tool_result.get('total_pages', '?')}):\n\n{tool_result['content']}"
                        else:
                            # Generic dict fallback
                            import json
                            try:
                                result_str = json.dumps(tool_result, indent=2)
                            except Exception:
                                result_str = str(tool_result)
                    else:
                        result_str = str(tool_result)
                    
                    # Limit result size to prevent context overflow
                    if len(result_str) > 2000:
                        result_str = result_str[:2000] + "... [truncated]"

                    # Add tool result to conversation history
                    tool_result_message = Message(
                        created_at=datetime.now(),
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        message_content=result_str,
                        requester=None,
                    )
                    conversation.add_message(tool_result_message)

                    # Store for sending back to LLM
                    tool_results.append(
                        {"tool_call_id": tool_id, "name": tool_name, "content": result_str}
                    )

                except Exception as e:
                    error_msg = f"Tool execution failed: {str(e)}"
                    await self.services.logging_service.error(
                        f"Failed to execute tool {tool_call.get('function', {}).get('name', 'unknown')}: {e}"
                    )

                    # Add error to conversation
                    tool_result_message = Message(
                        created_at=datetime.now(),
                        message_type=MessageType.TOOL_CALL_RESPONSE,
                        message_content=error_msg,
                        requester=None,
                    )
                    conversation.add_message(tool_result_message)

                    tool_results.append(
                        {
                            "tool_call_id": tool_call.get("id", "unknown"),
                            "name": tool_call.get("function", {}).get("name", "unknown"),
                            "content": error_msg,
                        }
                    )

            # After executing all tools, get the conversation messages and call LLM again
            # to get a proper response based on the tool results
            messages = await self._build_llm_messages(conversation)

            # Add a prompt to ask the model to respond about the tool execution
            # This ensures the model generates a user-facing response, not just thinking
            messages.append(
                {
                    "role": "user",
                    "content": "[System: The tool(s) have finished executing. The results are above. Please respond to the user confirming the action. Do NOT plan the action again.]",
                }
            )

            try:
                # Call LLM again with the updated conversation including tool results
                async with self.services.gpu_resource_manager.acquire_lock(
                    job_type="chatbot",
                    job_id=self.job_id,
                    metadata={
                        "thread_id": self.thread_id,
                        "conversation_id": self.conversation_id,
                        "phase": "tool_followup",
                    },
                ):
                    response = await self._call_llm(messages)

                    await self.services.logging_service.info(
                        f"Generated follow-up response after tool execution for thread {self.thread_id}"
                    )

                # Update content and thinking from the follow-up response
                content = response.content if hasattr(response, "content") else ""
                thinking_content = (
                    response.thinking if hasattr(response, "thinking") and response.thinking else ""
                )

            except Exception as e:
                await self.services.logging_service.error(
                    f"Failed to get follow-up response after tool execution: {e}"
                )
                # Fall back to a default message
                content = "I executed the requested action, but encountered an error generating a response."

        if not content:
            await self.services.logging_service.warning(
                f"Empty response from LLM for thread {self.thread_id}"
            )
            return

        # Treat content as chat response
        chat_content = content

        # Get Discord thread
        thread = await self._get_discord_thread()

        if not thread:
            await self.services.logging_service.error(
                f"Could not find Discord thread {self.thread_id}"
            )
            return

        # Send thinking message if present (italicized subtext)
        # But ONLY if thinking is different from content (some models use thinking field for main response)
        if thinking_content and thinking_content != content:
            # Format thinking for Discord: strip formatting, truncate, and italicize
            formatted_thinking = self._format_thinking_for_discord(thinking_content)

            # Store the FORMATTED (truncated) thinking in conversation history
            # This is what the user sees, not the full thinking process
            thinking_message = Message(
                created_at=datetime.now(),
                message_type=MessageType.THINKING,
                message_content=formatted_thinking,
                requester=None,
            )
            conversation.add_message(thinking_message)

            # Send the formatted thinking to Discord
            await thread.send(formatted_thinking)

        # Send chat message (normal)
        if chat_content:
            chat_message = Message(
                created_at=datetime.now(),
                message_type=MessageType.AI_RESPONSE,
                message_content=chat_content,
                requester=None,
            )
            conversation.add_message(chat_message)

            # Send to Discord with length validation (Discord limit is 2000 chars)
            # If message is too long, split it into chunks
            max_discord_length = 2000
            if len(chat_content) <= max_discord_length:
                await thread.send(chat_content)
            else:
                # Split message into chunks
                chunks = []
                current_chunk = ""

                # Split by lines to avoid breaking mid-sentence
                lines = chat_content.split("\n")
                for line in lines:
                    # If adding this line would exceed the limit, save current chunk and start new one
                    if len(current_chunk) + len(line) + 1 > max_discord_length:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = line
                    else:
                        if current_chunk:
                            current_chunk += "\n" + line
                        else:
                            current_chunk = line

                # Add the last chunk
                if current_chunk:
                    chunks.append(current_chunk)

                # Send each chunk
                for i, chunk in enumerate(chunks):
                    if i > 0:
                        # Add a small delay between chunks to avoid rate limiting
                        await asyncio.sleep(0.5)
                    await thread.send(chunk)

                await self.services.logging_service.info(
                    f"Split long message into {len(chunks)} chunks for thread {self.thread_id}"
                )

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

    def _format_thinking_for_discord(self, thinking_content: str, max_length: int = 200) -> str:
        """
        Format thinking content for Discord display.

        Strips all markdown formatting, truncates to max length, and wraps in italics.

        Args:
            thinking_content: Raw thinking content from LLM
            max_length: Maximum character length (default 200)

        Returns:
            Formatted thinking string for Discord (italicized subtext)
        """
        import re

        # Remove common markdown formatting
        cleaned = thinking_content

        # Remove bold/italic markers (**, *, __, _)
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)  # **bold**
        cleaned = re.sub(r"\*(.+?)\*", r"\1", cleaned)  # *italic*
        cleaned = re.sub(r"__(.+?)__", r"\1", cleaned)  # __underline__
        cleaned = re.sub(r"_(.+?)_", r"\1", cleaned)  # _italic_

        # Remove strikethrough (~~)
        cleaned = re.sub(r"~~(.+?)~~", r"\1", cleaned)

        # Remove inline code (`)
        cleaned = re.sub(r"`(.+?)`", r"\1", cleaned)

        # Remove code blocks (```)
        cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)

        # Remove headers (#, ##, ###, etc.)
        cleaned = re.sub(r"^#{1,6}\s*", "", cleaned, flags=re.MULTILINE)

        # Remove blockquotes (>)
        cleaned = re.sub(r"^>\s*", "", cleaned, flags=re.MULTILINE)

        # Remove links [text](url) -> text
        cleaned = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", cleaned)

        # Collapse multiple whitespace/newlines into single space
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Truncate to max length
        if len(cleaned) > max_length:
            cleaned = cleaned[: max_length - 3] + "..."

        # Wrap in Discord subtext and italics
        return f"-# *Thinking: {cleaned}*"

    async def _get_user_display_names(self, user_ids: list[str]) -> dict[str, str]:
        """
        Get display names with mentions for Discord user IDs.

        Args:
            user_ids: List of Discord user IDs

        Returns:
            Dictionary mapping user_id to "DisplayName <@user_id>"
        """
        user_names = {}

        try:
            # Get Discord thread to access guild
            thread = await self._get_discord_thread()

            if not thread or not thread.guild:
                # Fallback to user IDs with mention if we can't get the thread/guild
                return {user_id: f"User {user_id} <@{user_id}>" for user_id in user_ids}

            # Fetch member objects for each user
            for user_id in user_ids:
                try:
                    member = await thread.guild.fetch_member(int(user_id))
                    # Use display name (nickname if set, otherwise username) with mention
                    user_names[user_id] = f"{member.display_name} <@{user_id}>"
                except Exception as e:
                    # If we can't fetch a member, use a fallback with mention
                    await self.services.logging_service.debug(
                        f"Could not fetch member {user_id}: {e}"
                    )
                    user_names[user_id] = f"User {user_id} <@{user_id}>"

        except Exception as e:
            await self.services.logging_service.error(f"Failed to get user display names: {e}")
            # Fallback to user IDs with mention
            user_names = {user_id: f"User {user_id} <@{user_id}>" for user_id in user_ids}

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
    # Attachment Processing Methods
    # -------------------------------------------------------------- #

    async def _download_attachments_for_processing(self, attachments: list[dict]) -> list[dict]:
        """
        Download attachments to temporary storage for processing.

        Args:
            attachments: List of attachment metadata

        Returns:
            Updated attachment list with local_path added
        """
        from source.services.chat.chat_job_manager.attachment_utils import (
            download_attachments_batch,
        )

        await self.services.logging_service.info(
            f"[ATTACHMENTS] Starting download process for {len(attachments)} attachments in thread {self.thread_id}"
        )

        # Get temp directory from conversation file manager for conversation-related attachments
        temp_dir = self.services.conversation_file_service_manager.get_temp_storage_path()

        await self.services.logging_service.debug(f"[ATTACHMENTS] Temp directory: {temp_dir}")

        # Create a simple logger wrapper
        class LoggerWrapper:
            def __init__(self, logging_service, thread_id):
                self.logging_service = logging_service
                self.thread_id = thread_id

            def debug(self, msg):

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.logging_service.debug(msg))
                    else:
                        loop.run_until_complete(self.logging_service.debug(msg))
                except:
                    pass

            def info(self, msg):

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.logging_service.info(msg))
                    else:
                        loop.run_until_complete(self.logging_service.info(msg))
                except:
                    pass

            def warning(self, msg):

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.logging_service.warning(msg))
                    else:
                        loop.run_until_complete(self.logging_service.warning(msg))
                except:
                    pass

            def error(self, msg):

                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.logging_service.error(msg))
                    else:
                        loop.run_until_complete(self.logging_service.error(msg))
                except:
                    pass

        logger = LoggerWrapper(self.services.logging_service, self.thread_id)

        # Download attachments
        updated_attachments = await download_attachments_batch(
            attachments=attachments,
            temp_dir=temp_dir,
            max_size_mb=50,  # 50MB max per file
            logger=logger,
        )

        # Track downloaded attachments for cleanup
        self._downloaded_attachments.extend(updated_attachments)

        # Log detailed download summary
        downloaded_count = sum(1 for att in updated_attachments if att.get("downloaded") is True)
        failed_count = sum(
            1
            for att in updated_attachments
            if att.get("downloaded") is False
            and att.get("type") in ["file", "image", "video", "audio"]
        )

        if downloaded_count > 0:
            await self.services.logging_service.info(
                f"[ATTACHMENTS] Successfully downloaded {downloaded_count}/{len(attachments)} attachments for thread {self.thread_id}"
            )

        if failed_count > 0:
            await self.services.logging_service.warning(
                f"[ATTACHMENTS] Failed to download {failed_count} attachments for thread {self.thread_id}"
            )
            # Log details of failures
            for att in updated_attachments:
                if att.get("downloaded") is False and att.get("download_error"):
                    filename = att.get("filename", "unknown")
                    error = att.get("download_error", "unknown error")
                    await self.services.logging_service.warning(
                        f"[ATTACHMENTS] Failed: {filename} - {error}"
                    )

        return updated_attachments

    async def _cleanup_downloaded_attachments(self) -> None:
        """
        Clear the tracking list of downloaded attachments.
        Note: Files are persisted in temp storage and not deleted.
        They will be cleaned up on service restart.
        """
        if not self._downloaded_attachments:
            await self.services.logging_service.debug(
                f"[ATTACHMENTS] No attachments to clear from tracking for thread {self.thread_id}"
            )
            return

        count = len(self._downloaded_attachments)
        await self.services.logging_service.debug(
            f"[ATTACHMENTS] Clearing {count} attachments from tracking for thread {self.thread_id} (files persisted)"
        )

        # Clear the tracking list only - files remain in temp storage
        self._downloaded_attachments.clear()


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
        attachments: list[dict] | None = None,
    ) -> str:
        """
        Create and queue a new chat job.

        Args:
            thread_id: Discord thread ID
            conversation_id: SQL conversation ID
            message: User message to process
            user_id: Discord user ID
            attachments: Optional list of attachment metadata

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

        # If there are attachments, add them to the initial message queue
        if attachments:
            chat_job.message_queue.append(
                QueuedUserMessage(
                    user_id=user_id,
                    content=message,
                    timestamp=datetime.now(),
                    attachments=attachments,
                )
            )
            # Process the queued message with attachments instead of initial_message
            chat_job.initial_message = ""

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

    async def queue_user_message(
        self, thread_id: str, message: str, user_id: str, attachments: list[dict] | None = None
    ) -> bool:
        """
        Queue a user message to an active chat job.

        If the thread has an active job (AI is thinking), the message
        is added to the job's queue. Otherwise, a new job is created.

        Args:
            thread_id: Discord thread ID
            message: User message content
            user_id: Discord user ID
            attachments: Optional list of attachment metadata

        Returns:
            True if message was queued, False if new job needed
        """
        # Check if there's an active job for this thread
        active_job = self._active_jobs.get(thread_id)

        if active_job:
            # Add message to job's queue
            queued_msg = QueuedUserMessage(
                user_id=user_id,
                content=message,
                timestamp=datetime.now(),
                attachments=attachments or [],
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
