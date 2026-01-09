"""
User Query Handler Subroutine

Flow:
1. Entry (call_llm) -> Setup state
2. Update User (Brain) -> Explain action (Before) + Decide Tool
3. Execute Tools -> Run tool
4. Loop back to Update User -> Explain result (After) + Decide next
"""

import re
from typing import Any, Dict, List, Union

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.graph import END

from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.chat.mcp.subroutine_manager.subroutines.prompts import (
    USER_QUERY_HANDLER_SYSTEM_PROMPT,
)
from source.services.gpu.ollama_request_manager.manager import (
    Message as LLMMessage,
)


class UserQueryHandlerSubroutine(BaseSubroutine):
    def __init__(
        self,
        ollama_request_manager: Any,
        mcp_manager: Any,
        model: str = "gemma3:12b",
        on_step_end: Any = None,
    ):
        super().__init__(
            name="user_query_handler",
            description="Handles user queries with iterative tool calling.",
            input_schema={
                "type": "object",
                "properties": {"user_query": {"type": "string", "description": "The user's query"}},
                "required": ["user_query"],
            },
            on_step_end=on_step_end,
        )

        self.ollama_request_manager = ollama_request_manager
        self.mcp_manager = mcp_manager
        self.model = model

        # Virtual tool for explicitly ending the conversation
        self._finalize_tool_def = {
            "type": "function",
            "function": {
                "name": "finalize_response",
                "description": (
                    "Call this tool ONLY when you have completed the user's request "
                    "and have nothing left to do. You MUST provide a final response "
                    "message to the user explaining what you did or answering their "
                    "question BEFORE calling this tool. This ends the conversation."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }

        # --- SYSTEM PROMPT DEFINITION ---
        # This is the "God Instruction" that forces the model to behave.
        self._system_prompt = USER_QUERY_HANDLER_SYSTEM_PROMPT

        self._build_graph()

    def _build_graph(self):
        # 1. Add Nodes
        self.add_node("call_llm", self._process_input_node)
        self.add_node("update_user", self._update_user_node)
        self.add_node("execute_tools", self._execute_tools_node)

        # 2. Set Entry Point
        self.set_entry_point("call_llm")

        # 3. Define Flow

        # Entry -> Update User (The Brain)
        self.add_edge("call_llm", "update_user")

        # Update User -> (Router) -> Execute OR End
        self.add_conditional_edges(
            "update_user",
            self._router,
            {
                "execute_tools": "execute_tools",
                "end": END,
            },
        )

        # Execute -> Loop back to Update User (For the "After" update)
        self.add_edge("execute_tools", "update_user")

    # --- Helpers ---

    def _parse_tool_call(self, tool_call: Any) -> Dict | None:
        """
        Safely parse a tool call which might be a dict or an object.
        Returns a dict with keys: name, args, id.
        """
        try:
            # Case 1: Dictionary
            if isinstance(tool_call, dict):
                fn = tool_call.get("function", {})
                args = fn.get("arguments")
                if args is None:
                    args = {}

                return {
                    "name": fn.get("name"),
                    "args": args,
                    "id": tool_call.get("id", f"call_{fn.get('name', 'unknown')}"),
                }

            # Case 2: Object (Ollama/Pydantic)
            # Check for 'function' attribute
            if hasattr(tool_call, "function"):
                fn = tool_call.function
                # Function might be an object too
                name = getattr(fn, "name", None) or (
                    fn.get("name") if isinstance(fn, dict) else None
                )
                args = getattr(fn, "arguments", None) or (
                    fn.get("arguments") if isinstance(fn, dict) else None
                )

                if args is None:
                    args = {}

                # ID might be on the tool_call object
                tc_id = getattr(tool_call, "id", None) or f"call_{name}"

                return {"name": name, "args": args, "id": tc_id}

            return None
        except Exception as e:
            print(f"Error parsing tool call: {e}")
            return None

    def _clean_content(self, content: str) -> str:
        """
        Cleans the model output to prevent 'thinking' leakage.
        Handles both XML tags and common plain-text leakage patterns.
        """
        if not content:
            return ""

        # 1. Strip XML <think> tags (Case insensitive)
        cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE)

        # 2. Strip common third-person analysis patterns (Heuristic fallback)
        # Models sometimes start with "The user is asking..." when confused.
        # We strip this prefix if found at the very start.
        patterns = [
            r"^The user is asking:?\s*",
            r"^The user wants:?\s*",
            r"^User request:?\s*",
            r"^We need to:?\s*",
        ]
        for pattern in patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        return cleaned.strip()

    async def _convert_to_ollama_messages(self, messages: List[BaseMessage]) -> List[LLMMessage]:
        """
        Converts LangChain messages to Ollama format.
        Ensures the System Prompt is ALWAYS the first message.
        """
        # Start with the System Prompt
        ollama_msgs = [LLMMessage(role="system", content=self._system_prompt)]

        for msg in messages:
            if isinstance(msg, HumanMessage):
                ollama_msgs.append(LLMMessage(role="user", content=msg.content))

            elif isinstance(msg, SystemMessage):
                # We already added our main system prompt, but we append others if present
                ollama_msgs.append(LLMMessage(role="system", content=msg.content))

            elif isinstance(msg, AIMessage):
                # Clean assistant messages so history doesn't contain "thoughts"
                clean = self._clean_content(msg.content or "")
                ollama_msgs.append(LLMMessage(role="assistant", content=clean))

            elif isinstance(msg, ToolMessage):
                # Map Tool Result -> User Role
                # This is necessary for Ollama but creates the risk of the model
                # thinking it's reading a transcript. The System Prompt counters this.
                formatted = f"[Tool Result] (ID: {msg.tool_call_id})\n{msg.content}"
                ollama_msgs.append(LLMMessage(role="user", content=formatted))

        return ollama_msgs

    # --- Nodes ---

    async def _process_input_node(self, state: SubroutineState) -> Dict:
        """Entry Node: Pass-through."""
        return {}

    async def _update_user_node(self, state: SubroutineState) -> Dict:
        """
        THE BRAIN NODE.
        Decides actions and updates the user.
        """
        messages = state.get("messages", [])

        # Fetch tools
        tools = []
        if self.mcp_manager:
            try:
                tools = await self.mcp_manager.get_ollama_tools() or []
            except Exception as e:
                print(f"Warning: Failed to get tools: {e}")

        # Inject finalize tool
        if not any(t["function"]["name"] == "finalize_response" for t in tools):
            tools.append(self._finalize_tool_def)

        # Convert messages (System Prompt is added inside this method now)
        ollama_messages = await self._convert_to_ollama_messages(messages)

        try:
            response = await self.ollama_request_manager.query(
                model=self.model,
                messages=ollama_messages,
                stream=False,
                tools=tools,
            )

            raw_content = getattr(response, "content", "")

            # --- Clean content immediately ---
            clean_content = self._clean_content(raw_content)

            # Check for tool calls
            tool_calls = getattr(response, "tool_calls", None)

            # Safety fallback for empty content
            if tool_calls and not clean_content:
                # Check if finalize_response is being called
                is_finalizing = False
                for tc in tool_calls:
                    fn_name = None
                    if isinstance(tc, dict):
                        fn_name = tc.get("function", {}).get("name")
                    elif hasattr(tc, "function"):
                        fn = tc.function
                        if isinstance(fn, dict):
                            fn_name = fn.get("name")
                        else:
                            fn_name = getattr(fn, "name", None)

                    if fn_name == "finalize_response":
                        is_finalizing = True
                        break

                if is_finalizing:
                    clean_content = "I have completed your request."
                else:
                    clean_content = "I am processing your request..."
            elif not clean_content and not tool_calls:
                clean_content = "I have finished processing."

            lc_tool_calls = []
            if tool_calls:
                for tc in tool_calls:
                    parsed = self._parse_tool_call(tc)
                    if parsed:
                        lc_tool_calls.append(parsed)
                    else:
                        print(f"Warning: Skipping invalid tool call format: {tc}")

            ai_message = AIMessage(content=clean_content, tool_calls=lc_tool_calls)
            return {"messages": [ai_message]}

        except Exception as e:
            return {"messages": [AIMessage(content=f"Error in reasoning loop: {str(e)}")]}

    async def _execute_tools_node(self, state: SubroutineState) -> Dict:
        """Executes tools and returns results."""
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last_message = messages[-1]
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return {"messages": []}

        results = []
        for tool_call in last_message.tool_calls:
            try:
                # tool_call here is already a dict because it comes from AIMessage.tool_calls
                # which we populated in _update_user_node using _parse_tool_call
                if not isinstance(tool_call, dict):
                    print(f"Warning: Skipping invalid tool call in execute: {tool_call}")
                    continue

                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                if tool_name == "finalize_response":
                    # Virtual tool - acknowledge and pass through
                    results.append(ToolMessage(content="Response finalized.", tool_call_id=tool_id))
                    continue

                # Handle stop_conversation_monitoring specially
                if tool_name == "stop_conversation_monitoring":
                    try:
                        output = await self.mcp_manager.execute_tool(tool_name, tool_args)

                        # Format output
                        if isinstance(output, dict):
                            if "success" in output and output["success"]:
                                # Append the special marker to successful results
                                content_str = f"Result: {output.get('success', 'unknown')}"
                                if output.get("message"):
                                    content_str += f" - {output['message']}"
                                # Add the hardcoded marker
                                content_str += "\n\n[No Longer Monitoring Channel]"
                            else:
                                # Error case
                                content_str = f"Result: {output.get('success', 'unknown')}"
                                if output.get("error"):
                                    content_str += f" - Error: {output['error']}"
                        else:
                            content_str = str(output)

                        results.append(ToolMessage(content=content_str, tool_call_id=tool_id))
                    except Exception as e:
                        results.append(
                            ToolMessage(content=f"Error: {str(e)}", tool_call_id=tool_id)
                        )
                    continue

                try:
                    output = await self.mcp_manager.execute_tool(tool_name, tool_args)

                    # Format output
                    if isinstance(output, dict):
                        # Check for specific tool result formats
                        if "success" in output:
                            # Discord DM tool format
                            content_str = f"Result: {output.get('success', 'unknown')}"
                            if output.get("message"):
                                content_str += f" - {output['message']}"
                            if output.get("error"):
                                content_str += f" - Error: {output['error']}"
                        elif "results" in output:
                            # Google Search tool format
                            import json

                            content_str = json.dumps(output["results"], indent=2)
                        elif "content" in output and "url" in output:
                            # Read Webpage tool format
                            content_str = f"Content from {output['url']} (Page {output.get('current_page', 1)}/{output.get('total_pages', '?')}):\n\n{output['content']}"
                        else:
                            # Generic dict fallback
                            import json

                            try:
                                content_str = json.dumps(output, indent=2)
                            except Exception:
                                content_str = str(output)
                    else:
                        content_str = str(output)[:2000]

                    results.append(ToolMessage(content=content_str, tool_call_id=tool_id))
                except Exception as e:
                    results.append(ToolMessage(content=f"Error: {str(e)}", tool_call_id=tool_id))
            except Exception as e:
                print(f"Error processing tool call execution {tool_call}: {e}")
                continue

        return {"messages": results}

    def _router(self, state: SubroutineState) -> str:
        """Decides: Continue Loop OR End."""
        messages = state.get("messages", [])
        if not messages:
            return "end"

        last_message = messages[-1]

        if isinstance(last_message, AIMessage):
            if last_message.tool_calls:
                # Check for finalize_response
                try:
                    has_finalize = any(
                        tc.get("name") == "finalize_response" for tc in last_message.tool_calls
                    )
                    has_other_tools = any(
                        tc.get("name") != "finalize_response" for tc in last_message.tool_calls
                    )
                except Exception as e:
                    print(f"Error in router tool check: {e}")
                    return "end"

                # If ONLY finalize is called, we end.
                # If other tools are present, we MUST execute them first.
                if has_finalize and not has_other_tools:
                    return "end"

                # Otherwise (other tools present, or no finalize), execute tools
                return "execute_tools"

            # If pure text (and cleaned), we end the turn
            return "end"

        return "end"


def create_user_query_handler_subroutine(
    ollama_request_manager: Any,
    mcp_manager: Any,
    model: str = "gemma3:12b",
    on_step_end: Any = None,
) -> UserQueryHandlerSubroutine:
    subroutine = UserQueryHandlerSubroutine(
        ollama_request_manager=ollama_request_manager,
        mcp_manager=mcp_manager,
        model=model,
        on_step_end=on_step_end,
    )
    subroutine.compile()
    return subroutine
