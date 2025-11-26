"""Example usage of the InMemoryConversationManager.

This file demonstrates how to use the conversation manager system.
"""

import asyncio
from datetime import datetime

from source.services.conversation_manager import (
    Conversation,
    InMemoryConversationManager,
    Message,
    MessageType,
)


async def example_basic_usage():
    """Example of basic conversation creation and message management."""
    print("=== Basic Usage Example ===\n")

    # Initialize the manager (without file manager for this example)
    manager = InMemoryConversationManager()

    # Create a new conversation
    conversation = manager.create_conversation(
        thread_id="1234567890",
        guild_id="987654321",
        guild_name="Example Server",
        requester="111111111111111111",
    )

    print(f"Created conversation with filename: {conversation.filename}")
    print(f"Thread ID: {conversation.thread_id}")
    print(f"Participants: {conversation.participants}\n")

    # Add a user message
    user_msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Hello, Echo! Can you help me?",
        requester="111111111111111111",
    )

    manager.add_message_to_conversation(
        thread_id="1234567890",
        message=user_msg,
    )

    print("Added user message")

    # Add AI thinking message
    thinking_msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.THINKING,
        message_content="Let me analyze your request...",
    )

    manager.add_message_to_conversation(
        thread_id="1234567890",
        message=thinking_msg,
    )

    print("Added thinking message")

    # Add AI response
    response_msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Of course! I'd be happy to help. What do you need?",
    )

    manager.add_message_to_conversation(
        thread_id="1234567890",
        message=response_msg,
    )

    print("Added response message\n")

    # Retrieve and display conversation
    conv = manager.get_conversation("1234567890")
    if conv:
        print(f"Conversation has {len(conv.history)} messages")
        print(f"Last updated: {conv.updated_at}")
        print(f"Participants: {conv.participants}\n")

    # Show JSON format
    print("Conversation JSON:")
    import json

    print(json.dumps(conv.to_json(), indent=2))

    # Cleanup
    await manager.shutdown()


async def example_tool_calls():
    """Example of handling tool calls in conversations."""
    print("\n\n=== Tool Call Example ===\n")

    manager = InMemoryConversationManager()

    conversation = manager.create_conversation(
        thread_id="9876543210",
        guild_id="123456789",
        guild_name="Tool Test Server",
        requester="222222222222222222",
    )

    # User asks a question that requires a tool
    user_msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Can you search for Python async documentation?",
        requester="222222222222222222",
    )

    manager.add_message_to_conversation("9876543210", user_msg)

    # AI decides to use a tool
    tool_call_msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.TOOL_CALL,
        message_content="Searching documentation database",
        tools=[
            {
                "name": "search_documents",
                "params": {
                    "query": "python async programming",
                    "limit": 5,
                    "filters": {"type": "documentation"},
                },
            }
        ],
    )

    manager.add_message_to_conversation("9876543210", tool_call_msg)

    # Tool returns results
    tool_response_msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.TOOL_CALL_RESPONSE,
        message_content="Found 5 relevant documents on Python async programming",
    )

    manager.add_message_to_conversation("9876543210", tool_response_msg)

    # AI responds with synthesized answer
    final_response = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="I found some great resources on Python async! Here's what I learned...",
    )

    manager.add_message_to_conversation("9876543210", final_response)

    # Display the conversation
    conv = manager.get_conversation("9876543210")
    if conv:
        print(f"Conversation has {len(conv.history)} messages")
        for i, msg in enumerate(conv.history, 1):
            print(f"\nMessage {i}:")
            print(f"  Type: {msg.message_type.value}")
            print(f"  Content: {msg.message_content}")
            if msg.tools:
                print(f"  Tools: {msg.tools}")

    # Cleanup
    await manager.shutdown()


async def example_idle_cleanup():
    """Example demonstrating automatic cleanup after idle time."""
    print("\n\n=== Idle Cleanup Example ===\n")

    # Set idle time to 3 seconds for demonstration
    InMemoryConversationManager.IDLE_TIME = 3

    manager = InMemoryConversationManager()

    # Create a conversation
    conversation = manager.create_conversation(
        thread_id="5555555555",
        guild_id="444444444",
        guild_name="Cleanup Test",
        requester="333333333333333333",
    )

    print(f"Created conversation: {conversation.thread_id}")
    print(f"Active conversations: {len(manager.get_all_conversations())}")

    # Wait for 2 seconds
    print("\nWaiting 2 seconds...")
    await asyncio.sleep(2)

    # Add a message (resets idle timer)
    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="This message resets the idle timer",
        requester="333333333333333333",
    )

    manager.add_message_to_conversation("5555555555", msg)
    print("Added message - idle timer reset")
    print(f"Active conversations: {len(manager.get_all_conversations())}")

    # Wait for 2 more seconds (total 2 from reset)
    print("\nWaiting 2 more seconds...")
    await asyncio.sleep(2)
    print(f"Active conversations: {len(manager.get_all_conversations())}")

    # Wait for 2 more seconds (total 4 from reset - exceeds idle time)
    print("\nWaiting 2 more seconds (should trigger cleanup)...")
    await asyncio.sleep(2)
    print(f"Active conversations: {len(manager.get_all_conversations())}")
    print("Conversation was automatically cleaned up!")

    # Cleanup
    await manager.shutdown()

    # Reset to default
    InMemoryConversationManager.IDLE_TIME = 5 * 60


async def main():
    """Run all examples."""
    await example_basic_usage()
    await example_tool_calls()
    await example_idle_cleanup()

    print("\n\n=== All examples completed ===")


if __name__ == "__main__":
    asyncio.run(main())
