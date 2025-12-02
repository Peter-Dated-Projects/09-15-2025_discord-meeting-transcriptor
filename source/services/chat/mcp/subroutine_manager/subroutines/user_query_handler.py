"""
User Query Handler Subroutine

This subroutine handles user queries with LLM interaction and tool calling.
It follows a loop pattern:
1. User sends query → prompt LLM
2. If LLM requires tool call → execute tool
3. Check if LLM needs another tool call
4. If yes → repeat step 2, else respond to user and exit

This subroutine is designed to be used with the SubroutineManager.
"""

from typing import Any, Dict, List, Union

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.graph import END

# Adjust import path as needed based on your project structure
from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.gpu.ollama_request_manager.manager import (
    Message as LLMMessage,
)


class UserQueryHandlerSubroutine(BaseSubroutine):
    """
    A subroutine that handles user queries with iterative tool calling.

    This subroutine:
    - Prompts the LLM with user query and conversation context
    - Detects and executes tool calls from the LLM
    - Continues calling tools until the LLM is satisfied
    - Returns final response to the user
    """

    def __init__(
        self,
        ollama_request_manager: Any,
        mcp_manager: Any,
        model: str = "gemma3:12b",
        on_step_end: Any = None,
    ):
        """
        Initialize the UserQueryHandlerSubroutine.

        Args:
            ollama_request_manager: Manager for calling Ollama LLM
            mcp_manager: Manager for accessing and executing tools
            model: The Ollama model to use for queries
            on_step_end: Optional callback for step completion
        """
        super().__init__(
            name="user_query_handler",
            description=(
                "Handles user queries with LLM and tool calling capabilities. "
                "Iteratively calls tools until the query is fully resolved."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "user_query": {
                        "type": "string",
                        "description": "The user's query to process",
                    }
                },
                "required": ["user_query"],
            },
            on_step_end=on_step_end,
        )

        self.ollama_request_manager = ollama_request_manager
        self.mcp_manager = mcp_manager
        self.model = model

        # Build the graph structure using BaseSubroutine methods
        self._build_graph()

    def _build_graph(self):
        """Build the LangGraph workflow for user query handling."""
        # 1. Add Nodes
        self.add_node("call_llm", self._call_llm_node)
        self.add_node("execute_tools", self._execute_tools_node)
        self.add_node("finalize_response", self._finalize_response_node)

        # 2. Set Entry Point
        self.set_entry_point("call_llm")

        # 3. Add Conditional Logic
        # After calling LLM, check if tools are needed
        self.add_conditional_edges(
            "call_llm",
            self._should_execute_tools,
            {
                "execute_tools": "execute_tools",
                "finalize": "finalize_response",
            },
        )

        # After executing tools, loop back to LLM to process results
        self.add_edge("execute_tools", "call_llm")

        # 4. Set Finish Point
        self.set_finish_point("finalize_response")

    async def _call_llm_node(self, state: SubroutineState) -> Dict:
        """
        Call the LLM with current conversation context.
        """
        messages = state.get("messages", [])

        # Get available tools
        tools = None
        if self.mcp_manager:
            try:
                tools = await self.mcp_manager.get_ollama_tools()
            except Exception as e:
                # Log but continue without tools if manager fails
                print(f"Warning: Failed to get tools from MCP manager: {e}")

        # Convert to format expected by the specific Request Manager
        ollama_messages = await self._convert_to_ollama_messages(messages)

        try:
            response = await self.ollama_request_manager.query(
                model=self.model,
                messages=ollama_messages,
                temperature=0.7,
                stream=False,
                keep_alive="1m",
                tools=tools,
            )

            # safely extract content and tool_calls
            content = getattr(response, "content", "")
            tool_calls = getattr(response, "tool_calls", None)

            # Construct AIMessage
            if tool_calls:
                # Map Ollama response format to LangChain format
                lc_tool_calls = []
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    lc_tool_calls.append(
                        {
                            "name": fn.get("name"),
                            "args": fn.get("arguments"),
                            "id": tc.get("id", f"call_{fn.get('name', 'unknown')}"),
                        }
                    )

                ai_message = AIMessage(content=content or "", tool_calls=lc_tool_calls)
            else:
                ai_message = AIMessage(content=content)

            return {"messages": [ai_message]}

        except Exception as e:
            return {"messages": [AIMessage(content=f"Error interacting with LLM: {str(e)}")]}

    async def _execute_tools_node(self, state: SubroutineState) -> Dict:
        """
        Execute all tool calls found in the last AI message.
        """
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last_message = messages[-1]

        # Validation: Ensure we are acting on an AI message with tool calls
        if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
            return {"messages": []}

        results = []
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            tool_id = tool_call["id"]

            try:
                # Execute via manager
                output = await self.mcp_manager.execute_tool(tool_name, tool_args)

                # Format output as string
                if isinstance(output, dict):
                    content_str = f"Result: {output.get('success', 'unknown')}"
                    if output.get("message"):
                        content_str += f" - {output['message']}"
                    if output.get("error"):
                        content_str += f" - Error: {output['error']}"
                else:
                    content_str = str(output)[:2000]  # Truncate large outputs

                results.append(ToolMessage(content=content_str, tool_call_id=tool_id))

            except Exception as e:
                results.append(
                    ToolMessage(content=f"Tool Execution Error: {str(e)}", tool_call_id=tool_id)
                )

        return {"messages": results}

    def _should_execute_tools(self, state: SubroutineState) -> str:
        """
        Conditional Edge Logic: Check if the last message requested tools.
        """
        messages = state.get("messages", [])
        if not messages:
            return "finalize"

        last_message = messages[-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "execute_tools"

        return "finalize"

    async def _finalize_response_node(self, state: SubroutineState) -> Dict:
        """
        Decides if a final summary is needed.
        If tools were used, ask LLM to summarize findings.
        If no tools were used, the last LLM message is already the answer.
        """
        messages = state.get("messages", [])

        # Check history to see if any tools were actually used in this session
        has_tool_usage = any(isinstance(m, ToolMessage) for m in messages)

        if has_tool_usage:
            # Instruct LLM to synthesize tool outputs into a natural response
            final_prompt = HumanMessage(
                content=(
                    "The requested tools have been executed. Based on the results above, "
                    "please provide a clear, concise final answer to my original request."
                )
            )

            # Temporary state with the new prompt included
            ollama_messages = await self._convert_to_ollama_messages(messages + [final_prompt])

            try:
                response = await self.ollama_request_manager.query(
                    model=self.model,
                    messages=ollama_messages,
                    stream=False,
                    tools=None,  # Disable tools for final summary
                )

                content = getattr(response, "content", "Task completed.")
                return {"messages": [final_prompt, AIMessage(content=content)]}

            except Exception as e:
                return {
                    "messages": [
                        final_prompt,
                        AIMessage(content=f"Error generating final summary: {e}"),
                    ]
                }

        # If no tools were used, the previous AIMessage is the final answer.
        # We return empty dict so state remains unchanged.
        return {}

    async def _convert_to_ollama_messages(self, messages: List[BaseMessage]) -> List[LLMMessage]:
        """
        Convert LangChain message objects to the format expected by the
        Ollama Request Manager.
        """
        ollama_msgs = []

        for msg in messages:
            if isinstance(msg, HumanMessage):
                ollama_msgs.append(LLMMessage(role="user", content=msg.content))

            elif isinstance(msg, AIMessage):
                # Handle tool calls in AI message
                if msg.tool_calls:
                    # Note: Depending on your specific Ollama manager implementation,
                    # you might need to format tool_calls specifically here.
                    # This implementation passes content and assumes the manager handles metadata,
                    # or treats it as a standard assistant message if content exists.
                    ollama_msgs.append(LLMMessage(role="assistant", content=msg.content or ""))
                else:
                    ollama_msgs.append(LLMMessage(role="assistant", content=msg.content))

            elif isinstance(msg, ToolMessage):
                # Ollama often handles tool results best as user messages
                # with a specific prefix if native tool roles aren't fully supported
                # by the specific manager implementation.
                formatted_content = f"[Tool Result for ID {msg.tool_call_id}]\n{msg.content}"
                ollama_msgs.append(LLMMessage(role="user", content=formatted_content))

        return ollama_msgs


def create_user_query_handler_subroutine(
    ollama_request_manager: Any,
    mcp_manager: Any,
    model: str = "gemma3:12b",
    on_step_end: Any = None,
) -> UserQueryHandlerSubroutine:
    """
    Factory function to create and compile the subroutine.
    """
    subroutine = UserQueryHandlerSubroutine(
        ollama_request_manager=ollama_request_manager,
        mcp_manager=mcp_manager,
        model=model,
        on_step_end=on_step_end,
    )
    subroutine.compile()
    return subroutine
