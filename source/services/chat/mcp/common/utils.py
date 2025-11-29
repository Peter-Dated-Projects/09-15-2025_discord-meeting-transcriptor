"""
This module provides common utility functions for the MCP components.
"""
from typing import List
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
# Assuming the Message and MessageType classes are accessible for type hinting.
# A real implementation would need to adjust the import path.
from ....chat.conversation_manager.in_memory_cache import (
    Message,
    MessageType,
)


def convert_to_langchain_messages(
    messages: List[Message],
) -> List[BaseMessage]:
    """
    Converts a list of the project's custom Message objects into a list of
    LangChain BaseMessage objects.

    Args:
        messages (List[Message]): A list of custom Message objects from the conversation history.

    Returns:
        List[BaseMessage]: A list of LangChain message objects ready for use in LangGraph.
    """
    langchain_messages: List[BaseMessage] = []
    for msg in messages:
        if msg.message_type == MessageType.CHAT:
            # Check if the message content indicates it's from the AI or a user
            # This is a simplification; a more robust system might have a dedicated 'sender' field.
            if msg.requester:
                langchain_messages.append(HumanMessage(content=msg.message_content))
            else:
                langchain_messages.append(AIMessage(content=msg.message_content))
        
        elif msg.message_type == MessageType.TOOL_CALL:
            # This assumes the AI generated the tool call
            tool_calls = [
                {
                    "name": tool.get("name"),
                    "args": tool.get("args"),
                    "id": tool.get("id"),
                }
                for tool in msg.tools or []
            ]
            langchain_messages.append(AIMessage(content=msg.message_content, tool_calls=tool_calls))
        
        elif msg.message_type == MessageType.TOOL_CALL_RESPONSE:
            # A tool call response should be a ToolMessage
            # We need the tool_call_id from the original tool call.
            # This assumes the tool_call_id is stored in the message content or metadata.
            # For this example, we'll assume the content is the result and there's a tool_call_id in tools meta.
            if msg.tools:
                 for tool in msg.tools:
                      tool_call_id = tool.get("id")
                      if tool_call_id:
                           langchain_messages.append(
                                ToolMessage(content=msg.message_content, tool_call_id=tool_call_id)
                           )

    return langchain_messages
