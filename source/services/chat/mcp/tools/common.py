"""
Common tools and schemas used across multiple MCP subroutines and tools.
"""

# Tools for relevance filtering
RELEVANCE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_relevance",
            "description": "Set whether the item is relevant to the user query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "is_relevant": {
                        "type": "boolean",
                        "description": "True if the item is relevant, False otherwise.",
                    },
                    "one_sentence_summary": {
                        "type": "string",
                        "description": "A 1-sentence summary of why this item is relevant. Required if is_relevant is True.",
                    },
                },
                "required": ["is_relevant"],
            },
        },
    }
]


def get_finalize_tool_definition(
    name: str = "finalize",
    description: str = "Call this tool to indicate that you have completed the task.",
) -> dict:
    """
    Get a standardized definition for a finalize/finish tool.

    Args:
        name: The name of the tool (default: "finalize")
        description: The description of the tool

    Returns:
        Tool definition dictionary
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
