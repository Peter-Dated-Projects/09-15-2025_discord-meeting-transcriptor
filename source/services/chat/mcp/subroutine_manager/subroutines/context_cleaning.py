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

from typing import Any, Dict, List, Set

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END

from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.chat.conversation_manager.in_memory_cache import Conversation, MessageType
from source.services.gpu.ollama_request_manager.manager import LockedOllamaRequestManager
from source.services.chat.mcp.tools.common import get_finalize_tool_definition

# System prompt for the context cleaning specialist
CONTEXT_CLEANING_SYSTEM_PROMPT = """
You are a Context Management Specialist. Your goal is to optimize the conversation context for an AI assistant.
You will be provided with a numbered list of messages from the current conversation.
Your task is to identify messages that are no longer relevant, redundant, or trivial, and exclude them from the context.

Rules:
1.  Keep the most recent messages (last 5-10) to maintain immediate flow.
2.  Keep messages that contain important facts, user preferences, or ongoing tasks.
3.  Exclude simple acknowledgments (e.g., "Okay", "Thanks"), repetitive greetings, or resolved clarifications.
4.  Exclude intermediate "thinking" or "tool call" messages if they don't add value to the final result.
5.  Use the `exclude_message(index)` tool to remove a message from context.
6.  Use the `include_message(index)` tool to explicitly keep a message (if it was previously excluded or to be safe).
7.  When you are finished optimizing the context, call the `finished()` tool.

You must iterate through the messages and make decisions. You can process multiple messages in one turn by calling tools multiple times.
"""


class ContextCleaningSubroutine(BaseSubroutine):
    def __init__(
        self,
        ollama_request_manager: LockedOllamaRequestManager,
        conversation: Conversation,
        model: str = "gemma3:12b",
        on_step_end: Any = None,
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
            
            history_text += f"[{i}] {status} {sender}: {content}\n"

        messages = [
            SystemMessage(content=CONTEXT_CLEANING_SYSTEM_PROMPT),
            HumanMessage(content=history_text)
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
                    tool_calls.append({
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["args"]
                        },
                        "id": tc.get("id", "unknown")
                    })
                msg_dict["tool_calls"] = tool_calls
                
            ollama_messages.append(msg_dict)

        # Call Ollama
        response = await self.ollama_request_manager.query(
            model=self.model,
            messages=ollama_messages,
            tools=self.tools,
            temperature=0.1, # Low temperature for deterministic logic
        )

        # Convert response back to LangChain AIMessage
        content = response.content if hasattr(response, "content") else ""
        tool_calls = []
        
        if hasattr(response, "tool_calls") and response.tool_calls:
            for tc in response.tool_calls:
                tool_calls.append({
                    "name": tc["function"]["name"],
                    "args": tc["function"]["arguments"],
                    "id": tc.get("id", "unknown")
                })
        
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
                    else:
                        result_content = f"Error: Message index {idx} out of bounds."
                        
                elif tool_name == "include_message":
                    idx = args.get("message_index")
                    if self.conversation.set_message_context(idx, True):
                        result_content = f"Message {idx} included in context."
                    else:
                        result_content = f"Error: Message index {idx} out of bounds."
                        
                elif tool_name == "finished":
                    self.decisions_made = True
                    result_content = "Context cleaning finalized."
                    
                else:
                    result_content = f"Unknown tool: {tool_name}"
                    
            except Exception as e:
                result_content = f"Error executing {tool_name}: {str(e)}"

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
