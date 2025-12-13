"""
Meeting Search Subroutine

Flow:
1. Generate Queries -> LLM generates 2 search queries
2. Execute Search -> Run chroma search for each query
3. Synthesize -> LLM summarizes results
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

# System prompt for generating queries
GENERATE_QUERIES_PROMPT = """
You are an expert search query generator.
Your task is to generate 2 distinct search queries based on the user's request.
These queries will be used to search a vector database of meeting summaries.
The queries should be optimized for semantic search.

Output must be a JSON object with a single key "queries" containing a list of 2 strings.
Example:
{
    "queries": ["budget allocation 2024", "marketing strategy Q1"]
}
"""

# System prompt for synthesis
SYNTHESIS_PROMPT = """
You are a helpful assistant.
You have performed a search on meeting summaries and found the following results.
Your task is to provide a concise answer to the user's original request based on these results.
Include the meeting IDs and a short 1-2 sentence summary for each relevant meeting.
If no relevant information is found, state that.

User Request: {user_query}

Search Results:
{search_results}
"""

class MeetingSearchSubroutine(BaseSubroutine):
    def __init__(
        self,
        ollama_request_manager: Any,
        context: Any,
        model: str = "gemma3:12b",
        on_step_end: Any = None,
    ):
        super().__init__(
            name="meeting_search",
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
        self.add_node("synthesize", self._synthesize_node)

        self.set_entry_point("generate_queries")

        self.add_edge("generate_queries", "execute_search")
        self.add_edge("execute_search", "synthesize")
        self.add_edge("synthesize", END)

    async def _generate_queries_node(self, state: SubroutineState) -> Dict:
        messages = state["messages"]
        # The first message is expected to be the user query (HumanMessage)
        # or we can extract it from the last message if it's the start
        user_query = messages[-1].content

        prompt = [
            SystemMessage(content=GENERATE_QUERIES_PROMPT),
            HumanMessage(content=f"User Request: {user_query}"),
        ]

        response = await self.ollama_request_manager.query(
            messages=prompt,
            model=self.model,
            format="json",
        )
        
        # Store the generated queries in the state (as an AIMessage for history)
        return {"messages": [AIMessage(content=response)]}

    async def _execute_search_node(self, state: SubroutineState) -> Dict:
        messages = state["messages"]
        last_message = messages[-1]
        
        try:
            data = json.loads(last_message.content)
            queries = data.get("queries", [])
        except json.JSONDecodeError:
            # Fallback if JSON parsing fails
            queries = [messages[0].content] # Use original query

        all_results = []
        for query in queries:
            result = await query_chroma_summaries(query, self.context, n_results=3)
            if "results" in result:
                all_results.extend(result["results"])
        
        # Deduplicate results based on meeting_id
        seen_meetings = set()
        unique_results = []
        for res in all_results:
            if res["meeting_id"] not in seen_meetings:
                seen_meetings.add(res["meeting_id"])
                unique_results.append(res)
        
        # Store results as a JSON string in an AIMessage
        results_json = json.dumps(unique_results, indent=2)
        return {"messages": [AIMessage(content=results_json)]}

    async def _synthesize_node(self, state: SubroutineState) -> Dict:
        messages = state["messages"]
        results_json = messages[-1].content
        user_query = messages[0].content # Assuming first message is user query

        prompt = SYNTHESIS_PROMPT.format(
            user_query=user_query,
            search_results=results_json
        )

        response = await self.ollama_request_manager.query(
            messages=[HumanMessage(content=prompt)],
            model=self.model,
        )

        return {"messages": [AIMessage(content=response)]}


def create_meeting_search_subroutine(
    ollama_request_manager: Any,
    context: Any,
    model: str = "gemma3:12b",
) -> MeetingSearchSubroutine:
    """
    Factory function to create a MeetingSearchSubroutine.
    """
    return MeetingSearchSubroutine(
        ollama_request_manager=ollama_request_manager,
        context=context,
        model=model,
    )
