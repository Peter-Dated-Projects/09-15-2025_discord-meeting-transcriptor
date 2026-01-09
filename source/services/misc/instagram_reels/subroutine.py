"""
Instagram Reels Analysis Subroutine.

Uses a LangGraph agent to analyze Instagram Reels content (description + transcript)
and extract structured data using a specific tool call.
"""

import json
from typing import Any, Dict, List, Literal, TypedDict, Annotated
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage, SystemMessage
from langgraph.graph import END, StateGraph

try:
    from langgraph.graph import add_messages
except ImportError:
    from langgraph.graph.message import add_messages

from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState as BaseSubroutineState,
)
from source.services.gpu.ollama_request_manager.manager import (
    Message as LLMMessage,
)


# Extend the state to include inputs and outputs
class ReelsSubroutineState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]


SYSTEM_PROMPT = """You are an expert content analyst AI. Your task is to analyze the provided Instagram Reel description and audio transcript to generate a concise summary.

You have access to a tool called `return_summary`.
You must analyze the content and then call `return_summary` with the generated summary.

If the content is unclear or you need to "think" about it, you can output your thoughts before calling the tool.
However, the FINAL action must be calling the `return_summary` tool.

Do not just output JSON text. You MUST call the tool.
"""


class InstagramReelsAnalysisSubroutine(BaseSubroutine):
    def __init__(
        self,
        ollama_request_manager: Any,
        model: str = "ministral-3:3b",
    ):
        super().__init__(
            name="instagram_reels_analysis",
            description="Analyzes Instagram Reels content and generates a summary.",
            input_schema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Reel description"},
                    "transcript": {"type": "string", "description": "Reel audio transcript"},
                },
                "required": ["description", "transcript"],
            },
        )
        # Override the graph with our custom state
        self.graph = StateGraph(ReelsSubroutineState)

        self.ollama_request_manager = ollama_request_manager
        self.model = model

        # Define the tool for returning the summary
        self._return_summary_tool_def = {
            "type": "function",
            "function": {
                "name": "return_summary",
                "description": "Submit the final summary of the Instagram Reel.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "A concise summary of the reel content.",
                        },
                    },
                    "required": ["summary"],
                },
            },
        }

        self._build_graph()

    def _build_graph(self):
        self.add_node("entry", self._entry_node)
        self.add_node("agent", self._agent_node)
        self.add_node("tool_node", self._tool_node)
        self.add_node("extract_results", self._extract_results_node)

        self.set_entry_point("entry")

        self.add_edge("entry", "agent")

        self.add_conditional_edges(
            "agent",
            self._router,
            {
                "continue": "tool_node",
                "extract": "extract_results",
            },
        )

        self.add_edge("tool_node", "agent")
        self.add_edge("extract_results", END)

    async def _entry_node(self, state: ReelsSubroutineState) -> Dict[str, Any]:
        """Prepare the initial prompt."""
        # Use .get() carefully or check for keys. 'inputs' should exist if initialized correctly,
        # but for robustness:
        inputs = state.get("inputs", {})
        description = inputs.get("description", "")
        transcript = inputs.get("transcript", "")

        user_message = f"Please analyze this Instagram Reel.\n\nDescription: {description}\n\nTranscript: {transcript}"

        return {"messages": [HumanMessage(content=user_message)]}

    async def _agent_node(self, state: ReelsSubroutineState) -> Dict[str, Any]:
        """Call the LLM to decide what to do."""
        messages = state["messages"]

        # Convert LangChain messages to Ollama format if needed, but OllamaRequestManager might handle it?
        # Looking at OllamaRequestManager, it takes `messages: list[Message]`. `Message` is a TypedDict.
        # But `llm.invoke` (if using LangChain) takes BaseMessages.
        # Since we are using `ollama_request_manager.query`, we need to convert.

        ollama_messages = []

        # Add system prompt
        ollama_messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})

        for msg in messages:
            role = "user"
            content = ""
            if isinstance(msg, HumanMessage):
                role = "user"
                content = msg.content
            elif isinstance(msg, AIMessage):
                role = "assistant"
                content = msg.content
            elif isinstance(msg, ToolMessage):
                role = "tool"
                content = msg.content
                # Ollama currently supports tool messages differently depending on the version/interface.
                # The OllamaRequestManager seems to handle standard dicts.

            # Simple conversion provided the manager expects dicts
            ollama_messages.append({"role": role, "content": content})

        # Call Ollama
        # Pass the tool definition
        response = await self.ollama_request_manager.query(
            model=self.model,
            messages=ollama_messages,
            tools=[self._return_summary_tool_def],
            format=None,  # We want tool calls, so don't force JSON format on the text/response itself
        )

        # Convert response back to LangChain AIMessage
        content = response.content or ""
        tool_calls = response.tool_calls or []

        ai_message = AIMessage(content=content)
        if tool_calls:
            # Attach tool calls to the message for the router to see
            ai_message.tool_calls = []
            for tc in tool_calls:
                # Standardize tool call format for LangChain/LangGraph if needed
                # For our router, we just need to check if it exists
                ai_message.tool_calls.append(
                    {
                        "name": tc["function"]["name"],
                        "args": tc["function"]["arguments"],
                        "id": str(uuid.uuid4()),  # Generate a dummy ID if missing
                    }
                )

        return {"messages": [ai_message]}

    def _router(self, state: ReelsSubroutineState) -> Literal["continue", "extract"]:
        """Decide next step."""
        messages = state["messages"]
        last_message = messages[-1]

        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            # Check if it's the finishing tool
            for tool_call in last_message.tool_calls:
                if tool_call["name"] == "return_summary":
                    return "extract"

            return "continue"

        return "continue"

    async def _extract_results_node(self, state: ReelsSubroutineState) -> Dict[str, Any]:
        """Extract the final results from the tool call and persist to outputs."""
        messages = state["messages"]
        last_message = messages[-1]

        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            for tool_call in last_message.tool_calls:
                if tool_call["name"] == "return_summary":
                    try:
                        args = tool_call["args"]
                        if isinstance(args, str):
                            args = json.loads(args)

                        return {"outputs": args}
                    except Exception:
                        return {"outputs": {}}

        return {"outputs": {}}

    async def _tool_node(self, state: ReelsSubroutineState) -> Dict[str, Any]:
        """Execute tools (or handle missing/bad tools)."""
        messages = state["messages"]
        last_message = messages[-1]

        new_messages = []

        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            for tool_call in last_message.tool_calls:
                tool_name = tool_call["name"]

                if tool_name == "return_summary":
                    # This should have been caught by router and ended.
                    # If we are here, it means parsing failed or something.
                    new_messages.append(
                        ToolMessage(
                            tool_call_id=tool_call.get("id", "unknown"),
                            content="Error: Successfully called return_summary but failed to process arguments. Please ensure valid JSON arguments.",
                            name=tool_name,
                        )
                    )
                else:
                    # Unknown tool
                    new_messages.append(
                        ToolMessage(
                            tool_call_id=tool_call.get("id", "unknown"),
                            content=f"Error: Unknown tool '{tool_name}'. Please use 'return_summary'.",
                            name=tool_name,
                        )
                    )
        else:
            # No tool call was made, but we expected one
            new_messages.append(
                HumanMessage(
                    content="Please call the `return_summary` tool with the extracted data."
                )
            )

        return {"messages": new_messages}

    async def ainvoke(self, initial_state: Dict, config: Dict = None) -> Dict[str, Any]:
        """
        Async execution of the graph, returning the valid output.
        """
        self._step_count = 0
        if self._compiled_graph is None:
            self.compile()

        # Helper to init 'inputs' if passed in flat
        if "inputs" not in initial_state and (
            "description" in initial_state or "transcript" in initial_state
        ):
            real_initial_state = {
                "inputs": initial_state,
                "messages": initial_state.get("messages", []),
                "outputs": {},  # Initialize outputs
            }
        else:
            real_initial_state = initial_state
            if "outputs" not in real_initial_state:
                real_initial_state["outputs"] = {}  # Initialize outputs

        final_state = await self._compiled_graph.ainvoke(real_initial_state, config=config)

        # Return the extracted output
        return final_state.get("outputs", {})
