"""
Meeting Search by Summary Subroutine

Flow:
1. Generate Queries -> LLM generates 2 search queries
2. Execute Search -> Run chroma search for each query
"""

import json
from typing import Any, Dict, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END

from source.services.chat.mcp.common.langgraph_subroutine import (
    BaseSubroutine,
    SubroutineState,
)
from source.services.chat.mcp.tools.chroma_search_tool import query_chroma_summaries
from source.services.chat.mcp.tools.common import RELEVANCE_TOOLS

# System prompt for generating queries
GENERATE_QUERIES_PROMPT = """
You are an expert search query generator.
Your task is to generate 3 distinct search queries based on the user's request.
These queries will be used to search a vector database of meeting summaries.
The queries should be optimized for semantic search.

Output must be a JSON object with a single key "queries" containing a list of 3 strings.
Example:

User asks for "software"
{
    "queries": ["software development engineering", "app game mobile desktop", "webapp websites webapplication"]
}
"""


class MeetingSearchBySummarySubroutine(BaseSubroutine):
    def __init__(
        self,
        ollama_request_manager: Any,
        context: Any,
        model: str = "gemma3:12b",
        on_step_end: Any = None,
    ):
        super().__init__(
            name="meeting_search_by_summary",
            description="Search for past meetings and summarize results.",
            input_schema={
                "type": "object",
                "properties": {"user_query": {"type": "string", "description": "The user's query"}},
                "required": ["user_query"],
            },
            on_step_end=on_step_end,
        )

        self.ollama_request_manager = ollama_request_manager
        self.context = context
        self.model = model

        self._build_graph()

    def _build_graph(self):
        self.add_node("generate_queries", self._generate_queries_node)
        self.add_node("execute_search", self._execute_search_node)
        self.add_node("filter_results", self._filter_results_node)

        self.set_entry_point("generate_queries")

        self.add_edge("generate_queries", "execute_search")
        self.add_edge("execute_search", "filter_results")
        self.add_edge("filter_results", END)

    async def _generate_queries_node(self, state: SubroutineState) -> Dict:
        messages = state["messages"]
        # The first message is expected to be the user query (HumanMessage)
        # or we can extract it from the last message if it's the start
        user_query = messages[-1].content

        # Convert to Ollama-compatible message format (dicts)
        prompt = [
            {"role": "system", "content": GENERATE_QUERIES_PROMPT},
            {"role": "user", "content": f"User Request: {user_query}"},
        ]

        response = await self.ollama_request_manager.query(
            messages=prompt,
            model=self.model,
            format="json",
        )

        # Store the generated queries in the state (as an AIMessage for history)
        return {
            "messages": [
                AIMessage(
                    content=response.content if hasattr(response, "content") else str(response)
                )
            ]
        }

    async def _execute_search_node(self, state: SubroutineState) -> Dict:
        messages = state["messages"]
        last_message = messages[-1]

        try:
            data = json.loads(last_message.content)
            queries = data.get("queries", [])
        except json.JSONDecodeError:
            # Fallback if JSON parsing fails
            queries = [messages[0].content]  # Use original query

        all_results = []
        errors = []

        # Execute all queries in a single batch to save on model loading time
        result = await query_chroma_summaries(queries, self.context, n_results=3)

        if "results" in result:
            all_results.extend(result["results"])
        if "error" in result:
            errors.append(f"Batch search failed: {result['error']}")
            return {"messages": [AIMessage(content=json.dumps({"errors": errors}, indent=2))]}

        # Sort all results by distance (ascending) to prioritize best matches
        all_results.sort(key=lambda x: x.get("distance", 1.0))

        # Limit to top 10 results to avoid context overflow
        final_results = all_results[:10]

        # Truncate summary text to avoid token limits
        for res in final_results:
            if "summary_text" in res and len(res["summary_text"]) > 1000:
                res["summary_text"] = res["summary_text"][:1000] + "...(truncated)"

        # Store results as a JSON string in an AIMessage
        results_json = json.dumps(final_results, indent=2)
        return {"messages": [AIMessage(content=results_json)]}

    async def _filter_results_node(self, state: SubroutineState) -> Dict:
        messages = state["messages"]
        results_json = messages[-1].content
        user_query = messages[0].content  # Assuming first message is user query

        try:
            results = json.loads(results_json)
        except json.JSONDecodeError:
            return {"messages": [AIMessage(content="[]")]}

        filtered_results = []

        # Iterate through each result and ask LLM for relevance
        for res in results:
            summary = res.get("summary_text", "")
            meeting_id = res.get("meeting_id", "unknown")
            distance = res.get("distance", 1.0)
            filtered_results.append(
                {
                    "meeting_id": meeting_id,
                    "summary": summary,
                    "distance": distance,
                }
            )

        # Store filtered results as JSON
        return {"messages": [AIMessage(content=json.dumps(filtered_results, indent=2))]}


def create_meeting_search_by_summary_subroutine(
    ollama_request_manager: Any,
    context: Any,
    model: str = "gemma3:12b",
) -> MeetingSearchBySummarySubroutine:
    """
    Factory function to create a MeetingSearchBySummarySubroutine.
    """
    return MeetingSearchBySummarySubroutine(
        ollama_request_manager=ollama_request_manager,
        context=context,
        model=model,
    )
