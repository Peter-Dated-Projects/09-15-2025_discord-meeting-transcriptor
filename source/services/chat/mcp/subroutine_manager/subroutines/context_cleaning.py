"""
Context Cleaning Subroutine

This subroutine is responsible for analyzing the conversation history and
deciding which messages should be kept in the context and which should be
excluded to maintain a concise and relevant context window.

Flow:
1. Entry -> Format Conversation & Call LLM
2. LLM Decides -> Tool Calls (exclude/include messages)
3. Execute Tools -> Update Conversation
4. Loop until done
"""

from typing import Any, Dict, List, Set, Optional

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END

from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.chat.conversation_manager.in_memory_cache import (
    Conversation,
    MessageType,
    Message,
)
from source.services.chat.mcp.tools.common import get_finalize_tool_definition
from datetime import datetime

# System prompt for the context cleaning specialist
CONTEXT_CLEANING_SYSTEM_PROMPT = """
You are a Context Management Specialist. Your goal is to optimize the conversation context for an AI assistant.
You will be provided with a numbered list of messages from the current conversation.
Your task is to identify messages that are no longer relevant, redundant, or trivial, and exclude them from the context.

The goal is to reduce the context to approximately 10-15 high-value messages.
Currently, all messages are marked as context. You must summarize or remove messages to reach this target.

Rules:
1.  Keep the most recent messages (last 5-10) to maintain immediate flow.
2.  Keep messages that contain important facts, user preferences, or ongoing tasks.
3.  Exclude simple acknowledgments (e.g., "Okay", "Thanks"), repetitive greetings, or resolved clarifications.
4.  Exclude intermediate "thinking" or "tool call" messages if they don't add value to the final result.
5.  Use the `exclude_message(index)` tool to remove a message from context.
6.  Use the `include_message(index)` tool to explicitly keep a message (if it was previously excluded or to be safe).
7.  Use the `summarize_messages(message_uuids)` tool to replace a group of messages with a concise summary. This is useful for older parts of the conversation.
8.  When you are finished optimizing the context and have reached the target size (10-15 messages), call the `finished()` tool.

You must iterate through the messages and make decisions. You can process multiple messages in one turn by calling tools multiple times.
"""


class InMemoryLogger:
    def __init__(self):
        self.logs = []

    async def debug(self, message: str):
        self.logs.append({"level": "DEBUG", "message": message, "timestamp": datetime.now().isoformat()})

    async def info(self, message: str):
        self.logs.append({"level": "INFO", "message": message, "timestamp": datetime.now().isoformat()})

    async def error(self, message: str):
        self.logs.append({"level": "ERROR", "message": message, "timestamp": datetime.now().isoformat()})
    
    async def warning(self, message: str):
        self.logs.append({"level": "WARNING", "message": message, "timestamp": datetime.now().isoformat()})


class ContextCleaningSubroutine(BaseSubroutine):
    def __init__(
        self,
        ollama_request_manager: Any,
        conversation: Conversation,
        model: str = "gemma3:12b",
        on_step_end: Any = None,
        logging_service: Any = None,
    ):
        super().__init__(
            name="context_cleaning",
            description="Analyzes and cleans conversation context.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            on_step_end=on_step_end,
        )

        self.ollama_request_manager = ollama_request_manager
        self.conversation = conversation
        self.model = model
        self.logging_service = logging_service
        self.decisions_made = False

        # Define tools
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "exclude_message",
                    "description": "Exclude a message from the context window.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message_index": {
                                "type": "integer",
                                "description": "The index of the message to exclude.",
                            }
                        },
                        "required": ["message_index"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "include_message",
                    "description": "Include a message in the context window.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message_index": {
                                "type": "integer",
                                "description": "The index of the message to include.",
                            }
                        },
                        "required": ["message_index"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "summarize_messages",
                    "description": "Summarize a group of messages and replace them with a summary message.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message_uuids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "The UUIDs of the messages to summarize.",
                            }
                        },
                        "required": ["message_uuids"],
                    },
                },
            },
            get_finalize_tool_definition(
                name="finished",
                description="Signal that context cleaning is complete.",
            ),
        ]

        self._build_graph()

    def _build_graph(self):
        # 1. Add Nodes
        self.add_node("prepare_input", self._prepare_input_node)
        self.add_node("call_llm", self._call_llm_node)
        self.add_node("execute_tools", self._execute_tools_node)

        # 2. Set Entry Point
        self.set_entry_point("prepare_input")

        # 3. Define Flow
        self.add_edge("prepare_input", "call_llm")

        # Router: Execute Tools or End
        self.add_conditional_edges(
            "call_llm",
            self._router,
            {
                "execute_tools": "execute_tools",
                "end": END,
            },
        )

        # Loop back
        self.add_edge("execute_tools", "call_llm")

    # --- Nodes ---

    async def _prepare_input_node(self, state: SubroutineState) -> Dict:
        """
        Prepares the initial prompt with the conversation history.
        """
        # Format conversation history
        history_text = "Current Conversation History:\n"
        for i, msg in enumerate(self.conversation.history):
            # Determine sender
            sender = "System"
            if msg.message_type == MessageType.CHAT:
                sender = f"User ({msg.requester})" if msg.requester else "User"
            elif msg.message_type == MessageType.AI_RESPONSE:
                sender = "AI"
            elif msg.message_type == MessageType.TOOL_CALL:
                sender = "Tool Call"
            elif msg.message_type == MessageType.TOOL_CALL_RESPONSE:
                sender = "Tool Result"
            elif msg.message_type == MessageType.THINKING:
                sender = "AI Thought"

            # Status
            status = "[KEPT]" if msg.is_context else "[EXCLUDED]"

            # Truncate content for display if too long
            content = msg.message_content
            if len(content) > 200:
                content = content[:200] + "..."

            history_text += f"[{i}] (ID: {msg.uuid}) {status} {sender}: {content}\n"

        messages = [
            SystemMessage(content=CONTEXT_CLEANING_SYSTEM_PROMPT),
            HumanMessage(content=history_text),
        ]

        return {"messages": messages}

    async def _call_llm_node(self, state: SubroutineState) -> Dict:
        """
        Calls the LLM with the current state.
        """
        messages = state["messages"]

        # Convert LangChain messages to Ollama format
        ollama_messages = []
        for msg in messages:
            role = "user"
            if isinstance(msg, SystemMessage):
                role = "system"
            elif isinstance(msg, AIMessage):
                role = "assistant"
            elif isinstance(msg, ToolMessage):
                role = "tool"

            content = str(msg.content)

            msg_dict = {"role": role, "content": content}

            # Handle tool calls in AIMessage
            if isinstance(msg, AIMessage) and msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    tool_calls.append(
                        {
                            "function": {"name": tc["name"], "arguments": tc["args"]},
                            "id": tc.get("id", "unknown"),
                        }
                    )
                msg_dict["tool_calls"] = tool_calls

            ollama_messages.append(msg_dict)

        if self.logging_service:
            await self.logging_service.debug(
                f"[ContextCleaning] Sending {len(ollama_messages)} messages to LLM."
            )

        # Call Ollama
        response = await self.ollama_request_manager.query(
            model=self.model,
            messages=ollama_messages,
            tools=self.tools,
            temperature=0.1,  # Low temperature for deterministic logic
        )

        # Convert response back to LangChain AIMessage
        content = response.content if hasattr(response, "content") else ""
        tool_calls = []

        if hasattr(response, "tool_calls") and response.tool_calls:
            if self.logging_service:
                await self.logging_service.info(
                    f"[ContextCleaning] LLM Tool Calls: {response.tool_calls}"
                )

            for tc in response.tool_calls:
                tool_calls.append(
                    {
                        "name": tc["function"]["name"],
                        "args": tc["function"]["arguments"],
                        "id": tc.get("id", "unknown"),
                    }
                )

        if self.logging_service:
            await self.logging_service.debug(f"[ContextCleaning] LLM Response Content: {content}")

        ai_message = AIMessage(content=content, tool_calls=tool_calls)

        return {"messages": [ai_message]}

    async def _execute_tools_node(self, state: SubroutineState) -> Dict:
        """
        Executes the tools requested by the LLM.
        """
        last_message = state["messages"][-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return {"messages": []}

        results = []
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            args = tool_call["args"]
            tool_call_id = tool_call["id"]

            result_content = ""

            try:
                if tool_name == "exclude_message":
                    idx = args.get("message_index")
                    if self.conversation.set_message_context(idx, False):
                        result_content = f"Message {idx} excluded from context."
                        if self.logging_service:
                            await self.logging_service.debug(
                                f"[ContextCleaning] Excluded message {idx}"
                            )
                    else:
                        result_content = f"Error: Message index {idx} out of bounds."

                elif tool_name == "include_message":
                    idx = args.get("message_index")
                    if self.conversation.set_message_context(idx, True):
                        result_content = f"Message {idx} included in context."
                        if self.logging_service:
                            await self.logging_service.debug(
                                f"[ContextCleaning] Included message {idx}"
                            )
                    else:
                        result_content = f"Error: Message index {idx} out of bounds."

                elif tool_name == "summarize_messages":
                    uuids = args.get("message_uuids", [])
                    if not uuids:
                        result_content = "Error: No message UUIDs provided."
                    else:
                        # 1. Identify messages
                        messages_to_summarize = []
                        indices_to_hide = []

                        for i, msg in enumerate(self.conversation.history):
                            if msg.uuid in uuids:
                                messages_to_summarize.append(msg)
                                indices_to_hide.append(i)

                        if not messages_to_summarize:
                            result_content = "Error: No matching messages found for provided UUIDs."
                        else:
                            # 2. Run Summarization Job
                            if self.logging_service:
                                await self.logging_service.info(
                                    f"[ContextCleaning] Summarizing {len(messages_to_summarize)} messages..."
                                )

                            summary_text = await self._run_summarization_job(messages_to_summarize)

                            # 3. Create Summary Message
                            summary_msg = Message(
                                created_at=datetime.now(),
                                message_type=MessageType.SUMMARY,
                                message_content=summary_text,
                                summarized_content=uuids,
                                is_context=True,
                            )

                            # 4. Insert Summary Message
                            # We insert it after the last message being summarized
                            last_index = max(indices_to_hide)
                            self.conversation.history.insert(last_index + 1, summary_msg)

                            # 5. Hide original messages
                            # Note: Indices shift after insertion, but since we insert AFTER the last one,
                            # the indices of the messages BEFORE it (which are the ones we are hiding) remain valid?
                            # Wait, if we insert at last_index + 1, the indices <= last_index are unchanged.
                            # So we can safely use indices_to_hide.
                            for idx in indices_to_hide:
                                self.conversation.set_message_context(idx, False)

                            result_content = f"Summarized {len(messages_to_summarize)} messages. Summary added and originals excluded from context."
                            if self.logging_service:
                                await self.logging_service.info(
                                    f"[ContextCleaning] Summarization complete. Summary inserted at {last_index + 1}."
                                )

                elif tool_name == "finished":
                    self.decisions_made = True
                    result_content = "Context cleaning finalized."
                    if self.logging_service:
                        await self.logging_service.info("[ContextCleaning] Cleaning finalized.")

                else:
                    result_content = f"Unknown tool: {tool_name}"

            except Exception as e:
                result_content = f"Error executing {tool_name}: {str(e)}"
                if self.logging_service:
                    await self.logging_service.error(
                        f"[ContextCleaning] Error executing {tool_name}: {e}"
                    )

            results.append(ToolMessage(content=result_content, tool_call_id=tool_call_id))

        return {"messages": results}

    def _router(self, state: SubroutineState) -> str:
        """
        Decides whether to continue or end.
        """
        if self.decisions_made:
            return "end"

        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "execute_tools"

        # If no tool calls, maybe the model just chatted.
        # We should probably prompt it to finish or just end if it seems done.
        # For now, let's end to prevent infinite loops if it refuses to call tools.
        return "end"

    async def _run_summarization_job(self, messages: List[Any]) -> str:
        """
        Runs a summarization job on the provided messages.
        """
        # Format messages for summarization
        context_text = ""
        for msg in messages:
            sender = "User"
            if msg.requester:
                sender = f"User ({msg.requester})"
            elif msg.message_type == MessageType.AI_RESPONSE:
                sender = "AI"

            context_text += f"{sender}: {msg.message_content}\n"

        prompt = [
            {
                "role": "system",
                "content": "You are a helpful assistant that summarizes conversation segments.",
            },
            {
                "role": "user",
                "content": f"Please summarize the following conversation segment in concise point form:\n\n{context_text}",
            },
        ]

        if self.logging_service:
            await self.logging_service.debug(
                f"[ContextCleaning] Sending summarization request for {len(messages)} messages."
            )

        # Call LLM
        response = await self.ollama_request_manager.query(
            model=self.model,
            messages=prompt,
            temperature=0.3,
        )

        content = response.content if hasattr(response, "content") else "No summary generated."

        if self.logging_service:
            await self.logging_service.debug(f"[ContextCleaning] Summarization response: {content}")

        return content

    async def ainvoke(
        self, initial_state: Dict, config: Dict = None
    ) -> Optional[List[BaseMessage]]:
        """
        Async execution of the graph with logging interception.
        """
        start_time = datetime.now().isoformat()
        
        # Swap logger
        original_logger = self.logging_service
        memory_logger = InMemoryLogger()
        self.logging_service = memory_logger
        
        try:
            result = await super().ainvoke(initial_state, config)
        finally:
            # Restore logger
            self.logging_service = original_logger
            
            end_time = datetime.now().isoformat()
            
            # Collect active objects (messages in context)
            active_objects = [msg.to_json() for msg in self.conversation.history if msg.is_context]
            
            log_entry = {
                "start_time": start_time,
                "end_time": end_time,
                "active_objects_after_clean": active_objects,
                "logs": memory_logger.logs
            }
            
            self.conversation.cleanup_log.append(log_entry)
            
            # Save conversation
            if self.conversation.conversation_file_manager:
                await self.conversation.save_conversation()
            
        return result
