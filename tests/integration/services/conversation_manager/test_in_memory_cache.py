"""Unit tests for the InMemoryConversationManager.

Run with: pytest source/services/conversation_manager/test_in_memory_cache.py
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from source.services.conversation_manager import (
    Conversation,
    InMemoryConversationManager,
    Message,
    MessageType,
)

# -------------------------------------------------------------- #
# Message Tests
# -------------------------------------------------------------- #


def test_message_creation():
    """Test creating a basic message."""
    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Test message",
    )

    assert msg.message_content == "Test message"
    assert msg.message_type == MessageType.CHAT
    assert msg.tools is None
    assert msg.requester is None


def test_message_with_requester():
    """Test creating a message with requester."""
    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="User message",
        requester="123456789",
    )

    assert msg.requester == "123456789"


def test_message_with_tools():
    """Test creating a tool call message."""
    tools = [{"name": "search", "params": {"query": "test"}}]

    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.TOOL_CALL,
        message_content="Calling tool",
        tools=tools,
    )

    assert msg.tools == tools
    assert msg.message_type == MessageType.TOOL_CALL


def test_message_to_json():
    """Test converting message to JSON."""
    now = datetime.now()
    msg = Message(
        created_at=now,
        message_type=MessageType.CHAT,
        message_content="Test",
        requester="123",
    )

    json_data = msg.to_json()

    assert json_data["created_at"] == now.isoformat()
    assert json_data["message_type"] == "chat"
    assert json_data["message_content"] == "Test"
    assert json_data["meta"]["requester"] == "123"


def test_message_from_json():
    """Test creating message from JSON."""
    json_data = {
        "created_at": "2025-11-25T10:30:00",
        "message_type": "chat",
        "message_content": "Test message",
        "meta": {"requester": "123456"},
    }

    msg = Message.from_json(json_data)

    assert msg.message_type == MessageType.CHAT
    assert msg.message_content == "Test message"
    assert msg.requester == "123456"


def test_message_tool_call_json():
    """Test tool call message JSON conversion."""
    tools = [
        {
            "name": "search_docs",
            "params": {"query": "python", "limit": 5},
        }
    ]

    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.TOOL_CALL,
        message_content="Searching",
        tools=tools,
    )

    json_data = msg.to_json()

    assert json_data["meta"]["tools"] == tools
    assert "requester" not in json_data["meta"]


# -------------------------------------------------------------- #
# Conversation Tests
# -------------------------------------------------------------- #


def test_conversation_creation():
    """Test creating a basic conversation."""
    now = datetime.now()
    conv = Conversation(
        thread_id="123",
        created_at=now,
        guild_id="456",
        guild_name="Test Guild",
        requester="789",
    )

    assert conv.thread_id == "123"
    assert conv.guild_id == "456"
    assert conv.guild_name == "Test Guild"
    assert conv.requester == "789"
    assert conv.updated_at == now
    assert conv.participants == ["789"]
    assert len(conv.history) == 0


def test_conversation_filename_generation():
    """Test automatic filename generation."""
    now = datetime(2025, 11, 25, 10, 30, 0)
    conv = Conversation(
        thread_id="123",
        created_at=now,
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    expected = "2025-11-25_conversation-with-789-in-456.json"
    assert conv.filename == expected


def test_conversation_add_message():
    """Test adding messages to conversation."""
    conv = Conversation(
        thread_id="123",
        created_at=datetime.now(),
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Hello",
        requester="789",
    )

    conv.add_message(msg)

    assert len(conv.history) == 1
    assert conv.history[0] == msg


def test_conversation_participant_tracking():
    """Test automatic participant tracking."""
    conv = Conversation(
        thread_id="123",
        created_at=datetime.now(),
        guild_id="456",
        guild_name="Test",
        requester="111",
    )

    # Original requester is in participants
    assert "111" in conv.participants

    # Add message from same user
    msg1 = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Hello",
        requester="111",
    )
    conv.add_message(msg1)

    assert len(conv.participants) == 1

    # Add message from new user
    msg2 = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Hi!",
        requester="222",
    )
    conv.add_message(msg2)

    assert len(conv.participants) == 2
    assert "111" in conv.participants
    assert "222" in conv.participants


def test_conversation_to_json():
    """Test converting conversation to JSON."""
    now = datetime.now()
    conv = Conversation(
        thread_id="123",
        created_at=now,
        guild_id="456",
        guild_name="Test Guild",
        requester="789",
    )

    msg = Message(
        created_at=now,
        message_type=MessageType.CHAT,
        message_content="Test",
    )
    conv.add_message(msg)

    json_data = conv.to_json()

    assert json_data["guild_id"] == "456"
    assert json_data["guild_name"] == "Test Guild"
    assert json_data["requester"] == "789"
    assert json_data["participants"] == ["789"]
    assert len(json_data["history"]) == 1


@pytest.mark.asyncio
async def test_conversation_save_without_manager():
    """Test that saving without file manager raises error."""
    conv = Conversation(
        thread_id="123",
        created_at=datetime.now(),
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    with pytest.raises(ValueError, match="conversation_file_manager is not set"):
        await conv.save_conversation()


@pytest.mark.asyncio
async def test_conversation_save_new():
    """Test saving a new conversation."""
    mock_file_manager = AsyncMock()
    mock_file_manager.conversation_exists = AsyncMock(return_value=False)
    mock_file_manager.save_conversation = AsyncMock()

    conv = Conversation(
        thread_id="123",
        created_at=datetime.now(),
        guild_id="456",
        guild_name="Test",
        requester="789",
        conversation_file_manager=mock_file_manager,
    )

    success = await conv.save_conversation()

    assert success
    mock_file_manager.save_conversation.assert_called_once()


@pytest.mark.asyncio
async def test_conversation_save_existing():
    """Test updating an existing conversation."""
    mock_file_manager = AsyncMock()
    mock_file_manager.conversation_exists = AsyncMock(return_value=True)
    mock_file_manager.update_conversation = AsyncMock(return_value=True)

    conv = Conversation(
        thread_id="123",
        created_at=datetime.now(),
        guild_id="456",
        guild_name="Test",
        requester="789",
        conversation_file_manager=mock_file_manager,
    )

    success = await conv.save_conversation()

    assert success
    mock_file_manager.update_conversation.assert_called_once()


# -------------------------------------------------------------- #
# InMemoryConversationManager Tests
# -------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_manager_initialization():
    """Test manager initialization."""
    manager = InMemoryConversationManager()

    assert len(manager.conversations) == 0
    assert len(manager.cleanup_tasks) == 0
    assert manager.IDLE_TIME == 5 * 60


@pytest.mark.asyncio
async def test_manager_create_conversation():
    """Test creating a conversation."""
    manager = InMemoryConversationManager()

    conv = manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test Guild",
        requester="789",
    )

    assert conv.thread_id == "123"
    assert "123" in manager.conversations
    assert "123" in manager.cleanup_tasks

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_get_conversation():
    """Test retrieving a conversation."""
    manager = InMemoryConversationManager()

    manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    conv = manager.get_conversation("123")

    assert conv is not None
    assert conv.thread_id == "123"

    # Non-existent conversation
    assert manager.get_conversation("999") is None

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_add_message():
    """Test adding message to conversation."""
    manager = InMemoryConversationManager()

    manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Hello",
    )

    conv = manager.add_message_to_conversation("123", msg)

    assert conv is not None
    assert len(conv.history) == 1

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_remove_conversation():
    """Test removing a conversation."""
    manager = InMemoryConversationManager()

    manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    assert "123" in manager.conversations

    manager.remove_conversation("123")

    assert "123" not in manager.conversations
    assert "123" not in manager.cleanup_tasks


@pytest.mark.asyncio
async def test_manager_idle_cleanup():
    """Test automatic cleanup after idle time."""
    # Set short idle time for testing
    InMemoryConversationManager.IDLE_TIME = 1

    manager = InMemoryConversationManager()

    manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    assert "123" in manager.conversations

    # Wait for cleanup
    await asyncio.sleep(1.5)

    assert "123" not in manager.conversations

    await manager.shutdown()

    # Reset to default
    InMemoryConversationManager.IDLE_TIME = 5 * 60


@pytest.mark.asyncio
async def test_manager_reset_idle_timer():
    """Test that adding a message resets idle timer."""
    InMemoryConversationManager.IDLE_TIME = 2

    manager = InMemoryConversationManager()

    manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test",
        requester="789",
    )

    # Wait 1.5 seconds
    await asyncio.sleep(1.5)

    # Add message (should reset timer)
    msg = Message(
        created_at=datetime.now(),
        message_type=MessageType.CHAT,
        message_content="Reset",
    )
    manager.add_message_to_conversation("123", msg)

    # Wait another 1.5 seconds (total 3s from creation, but 1.5s from reset)
    await asyncio.sleep(1.5)

    # Should still exist
    assert "123" in manager.conversations

    # Wait another 1 second (2.5s from reset - should cleanup)
    await asyncio.sleep(1)

    assert "123" not in manager.conversations

    await manager.shutdown()

    InMemoryConversationManager.IDLE_TIME = 5 * 60


@pytest.mark.asyncio
async def test_manager_get_all_conversations():
    """Test getting all conversations."""
    manager = InMemoryConversationManager()

    manager.create_conversation("123", "456", "Guild1", "789")
    manager.create_conversation("456", "789", "Guild2", "012")

    all_convs = manager.get_all_conversations()

    assert len(all_convs) == 2
    assert "123" in all_convs
    assert "456" in all_convs

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_save_all_conversations():
    """Test saving all conversations."""
    mock_file_manager = AsyncMock()
    mock_file_manager.conversation_exists = AsyncMock(return_value=False)
    mock_file_manager.save_conversation = AsyncMock()

    manager = InMemoryConversationManager(conversation_file_manager=mock_file_manager)

    manager.create_conversation("123", "456", "Guild1", "789")
    manager.create_conversation("456", "789", "Guild2", "012")

    results = await manager.save_all_conversations()

    assert len(results) == 2
    assert results["123"] is True
    assert results["456"] is True

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_is_conversation_thread():
    """Test checking if a thread ID has an active conversation."""
    manager = InMemoryConversationManager()

    # Initially, no conversations exist
    assert manager.is_conversation_thread("123") is False

    # Create a conversation
    manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test Guild",
        requester="789",
    )

    # Now the thread should be recognized as a conversation thread
    assert manager.is_conversation_thread("123") is True

    # Non-existent thread should still return False
    assert manager.is_conversation_thread("999") is False

    # Remove the conversation
    manager.remove_conversation("123")

    # Thread should no longer be a conversation thread
    assert manager.is_conversation_thread("123") is False

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_known_thread_cache():
    """Test the known thread ID cache functionality."""
    manager = InMemoryConversationManager()

    # Initially, cache should be empty
    assert not manager.is_known_thread("123")
    assert len(manager.known_thread_ids) == 0

    # Create a conversation - should add to cache
    manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test Guild",
        requester="789",
    )

    # Thread should now be in cache
    assert manager.is_known_thread("123")
    assert "123" in manager.known_thread_ids

    # Different thread should not be in cache
    assert not manager.is_known_thread("999")

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_refresh_thread_id_cache():
    """Test refreshing thread ID cache from SQL."""
    manager = InMemoryConversationManager()

    # Mock SQL manager
    mock_sql_manager = AsyncMock()
    mock_sql_manager.get_all_thread_ids = AsyncMock(return_value=["thread1", "thread2", "thread3"])

    # Refresh cache
    count = await manager.refresh_thread_id_cache(mock_sql_manager)

    # Should have loaded 3 thread IDs
    assert count == 3
    assert len(manager.known_thread_ids) == 3
    assert manager.is_known_thread("thread1")
    assert manager.is_known_thread("thread2")
    assert manager.is_known_thread("thread3")
    assert not manager.is_known_thread("thread4")

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_load_conversation_already_in_memory():
    """Test loading a conversation that's already in memory."""
    manager = InMemoryConversationManager()

    # Create a conversation in memory
    original_conv = manager.create_conversation(
        thread_id="123",
        guild_id="456",
        guild_name="Test Guild",
        requester="789",
    )

    # Try to load it - should return the existing one
    mock_sql_manager = AsyncMock()
    mock_file_manager = AsyncMock()

    loaded_conv = await manager.load_conversation_from_storage(
        thread_id="123",
        conversations_sql_manager=mock_sql_manager,
        conversation_file_manager=mock_file_manager,
    )

    # Should return the same conversation object
    assert loaded_conv is original_conv
    assert loaded_conv.thread_id == "123"

    # SQL should not have been called since it's already in memory
    mock_sql_manager.retrieve_conversation_by_thread_id.assert_not_called()

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_load_conversation_from_sql_no_file():
    """Test loading a conversation from SQL when file doesn't exist."""
    mock_file_manager = AsyncMock()
    mock_file_manager.conversation_storage_path = "/tmp/nonexistent"

    manager = InMemoryConversationManager(conversation_file_manager=mock_file_manager)

    # Mock SQL manager returning conversation data
    mock_sql_manager = AsyncMock()
    mock_sql_manager.retrieve_conversation_by_thread_id = AsyncMock(
        return_value={
            "id": "conv123",
            "discord_thread_id": "thread456",
            "discord_guild_id": "guild789",
            "discord_requester_id": "user111",
            "created_at": "2025-11-25T10:30:00",
            "updated_at": "2025-11-25T10:35:00",
            "chat_meta": {"guild_name": "Test Server"},
        }
    )

    # Load conversation
    conversation = await manager.load_conversation_from_storage(
        thread_id="thread456",
        conversations_sql_manager=mock_sql_manager,
        conversation_file_manager=mock_file_manager,
    )

    # Should have created a minimal conversation
    assert conversation is not None
    assert conversation.thread_id == "thread456"
    assert conversation.guild_id == "guild789"
    assert conversation.requester == "user111"
    assert conversation.guild_name == "Test Server"

    # Should be in memory now
    assert manager.is_conversation_thread("thread456")
    assert manager.is_known_thread("thread456")

    # Should have scheduled cleanup
    assert "thread456" in manager.cleanup_tasks

    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_load_conversation_not_found():
    """Test loading a conversation that doesn't exist."""
    manager = InMemoryConversationManager()

    # Mock SQL manager returning None
    mock_sql_manager = AsyncMock()
    mock_sql_manager.retrieve_conversation_by_thread_id = AsyncMock(return_value=None)

    mock_file_manager = AsyncMock()

    # Try to load non-existent conversation
    conversation = await manager.load_conversation_from_storage(
        thread_id="nonexistent",
        conversations_sql_manager=mock_sql_manager,
        conversation_file_manager=mock_file_manager,
    )

    # Should return None
    assert conversation is None

    # Should not be in memory
    assert not manager.is_conversation_thread("nonexistent")

    await manager.shutdown()
