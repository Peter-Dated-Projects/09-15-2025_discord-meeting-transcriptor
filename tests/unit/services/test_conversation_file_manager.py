"""
Unit tests for ConversationFileManagerService.

Tests the conversation file management functionality including:
- Saving new conversations
- Updating existing conversations
- Retrieving conversations
- Deleting conversations
- File existence checks
- Listing conversations
"""

import os
from datetime import datetime

import pytest

from source.constructor import ServerManagerType
from source.context import Context
from source.server.constructor import construct_server_manager
from source.services.constructor import construct_services_manager


class TestConversationFileManagerService:
    """Test suite for ConversationFileManagerService."""

    @pytest.fixture
    async def setup(self, tmp_path, shared_test_log_file):
        """Setup test environment with services manager."""
        context = Context()

        # Initialize server manager
        servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
        context.set_server_manager(servers_manager)
        await servers_manager.connect_all()

        # Initialize services manager
        storage_path = os.path.join(str(tmp_path), "data")
        recording_storage_path = os.path.join(storage_path, "recordings")
        transcription_storage_path = os.path.join(storage_path, "transcriptions")
        conversation_storage_path = os.path.join(storage_path, "conversations")

        services_manager = construct_services_manager(
            ServerManagerType.DEVELOPMENT,
            context=context,
            storage_path=storage_path,
            recording_storage_path=recording_storage_path,
            transcription_storage_path=transcription_storage_path,
            conversation_storage_path=conversation_storage_path,
            log_file=shared_test_log_file,  # Use shared log file
            use_timestamp_logs=False,  # Don't create timestamp-based logs
        )
        await services_manager.initialize_all()

        yield services_manager, servers_manager

        # Cleanup
        await servers_manager.disconnect_all()

    @pytest.fixture
    def test_data(self):
        """Provide test data for conversations."""
        return {
            "discord_user_id": "123456789012345678",
            "guild_id": "987654321098765432",
            "thread_id": "112233445566778899",
            "conversation_data": {
                "messages": [
                    {"role": "user", "content": "Hello, Echo!"},
                    {"role": "assistant", "content": "Hello! How can I help you today?"},
                    {"role": "user", "content": "What's the weather like?"},
                    {
                        "role": "assistant",
                        "content": "I don't have access to real-time weather data.",
                    },
                ],
                "metadata": {
                    "created_at": datetime.now().isoformat(),
                    "total_messages": 4,
                },
            },
        }

    @pytest.mark.asyncio
    async def test_save_conversation(self, setup, test_data):
        """Test saving a new conversation."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Save conversation
        filename = await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
        )

        # Verify filename format
        assert filename.endswith(".json")
        # assert test_data["discord_user_id"] in filename  # User ID no longer in filename
        assert test_data["guild_id"] in filename
        assert test_data["thread_id"] in filename

        # Verify file exists
        exists = await conversation_manager.conversation_exists(filename)
        assert exists is True

    @pytest.mark.asyncio
    async def test_retrieve_conversation(self, setup, test_data):
        """Test retrieving a conversation."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Save conversation
        filename = await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
        )

        # Retrieve conversation
        retrieved_data = await conversation_manager.retrieve_conversation(filename)

        # Verify data matches
        assert retrieved_data is not None
        assert retrieved_data["messages"] == test_data["conversation_data"]["messages"]
        assert retrieved_data["metadata"]["total_messages"] == 4

    @pytest.mark.asyncio
    async def test_update_conversation(self, setup, test_data):
        """Test updating an existing conversation."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Save conversation
        filename = await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
        )

        # Update conversation with new message
        updated_data = test_data["conversation_data"].copy()
        updated_data["messages"].append({"role": "user", "content": "Thanks!"})
        updated_data["metadata"]["total_messages"] = 5

        success = await conversation_manager.update_conversation(filename, updated_data)
        assert success is True

        # Retrieve and verify update
        retrieved_data = await conversation_manager.retrieve_conversation(filename)
        assert len(retrieved_data["messages"]) == 5
        assert retrieved_data["messages"][-1]["content"] == "Thanks!"

    @pytest.mark.asyncio
    async def test_delete_conversation(self, setup, test_data):
        """Test deleting a conversation."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Save conversation
        filename = await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
        )

        # Verify it exists
        exists = await conversation_manager.conversation_exists(filename)
        assert exists is True

        # Delete conversation
        success = await conversation_manager.delete_conversation(filename)
        assert success is True

        # Verify it no longer exists
        exists = await conversation_manager.conversation_exists(filename)
        assert exists is False

    @pytest.mark.asyncio
    async def test_conversation_exists(self, setup, test_data):
        """Test checking if a conversation exists."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Check non-existent file
        fake_filename = "2025-01-01_conversation-with-fake-in-fake.json"
        exists = await conversation_manager.conversation_exists(fake_filename)
        assert exists is False

        # Save conversation
        filename = await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
        )

        # Check existing file
        exists = await conversation_manager.conversation_exists(filename)
        assert exists is True

    @pytest.mark.asyncio
    async def test_list_conversations(self, setup, test_data):
        """Test listing all conversations."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Initially should be empty
        conversations = await conversation_manager.list_conversations()
        assert len(conversations) == 0

        # Save multiple conversations
        user_ids = ["111111111111111111", "222222222222222222", "333333333333333333"]
        guild_id = test_data["guild_id"]
        thread_id = test_data["thread_id"]

        for i, user_id in enumerate(user_ids):
            await conversation_manager.save_conversation(
                conversation_data=test_data["conversation_data"],
                discord_user_id=user_id,
                guild_id=guild_id,
                thread_id=f"{thread_id}{i}",
            )

        # List conversations
        conversations = await conversation_manager.list_conversations()
        assert len(conversations) == 3

        # Verify all are JSON files
        for conv in conversations:
            assert conv.endswith(".json")

    @pytest.mark.asyncio
    async def test_get_conversation_by_user_and_guild_and_date(self, setup, test_data):
        """Test convenience method to get conversation by user, guild, and date."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Save conversation
        await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
        )

        # Retrieve using convenience method
        retrieved_data = await conversation_manager.get_conversation_by_user_and_guild_and_date(
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
            date=datetime.now(),
        )

        # Verify data
        assert retrieved_data is not None
        assert retrieved_data["messages"] == test_data["conversation_data"]["messages"]

    @pytest.mark.asyncio
    async def test_save_conversation_duplicate_raises_error(self, setup, test_data):
        """Test that saving a duplicate conversation raises FileExistsError."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Save conversation
        await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
        )

        # Try to save again with same parameters
        with pytest.raises(FileExistsError):
            await conversation_manager.save_conversation(
                conversation_data=test_data["conversation_data"],
                discord_user_id=test_data["discord_user_id"],
                guild_id=test_data["guild_id"],
                thread_id=test_data["thread_id"],
            )

    @pytest.mark.asyncio
    async def test_update_nonexistent_conversation_returns_false(self, setup, test_data):
        """Test that updating a non-existent conversation returns False."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Try to update non-existent file
        fake_filename = "2025-01-01_conversation-with-fake-in-fake.json"
        success = await conversation_manager.update_conversation(
            fake_filename, test_data["conversation_data"]
        )
        assert success is False

    @pytest.mark.asyncio
    async def test_retrieve_nonexistent_conversation_returns_none(self, setup):
        """Test that retrieving a non-existent conversation returns None."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Try to retrieve non-existent file
        fake_filename = "2025-01-01_conversation-with-fake-in-fake.json"
        data = await conversation_manager.retrieve_conversation(fake_filename)
        assert data is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_conversation_returns_false(self, setup):
        """Test that deleting a non-existent conversation returns False."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        # Try to delete non-existent file
        fake_filename = "2025-01-01_conversation-with-fake-in-fake.json"
        success = await conversation_manager.delete_conversation(fake_filename)
        assert success is False

    @pytest.mark.asyncio
    async def test_filename_format(self, setup, test_data):
        """Test that the filename format is correct."""
        services_manager, servers_manager = await anext(setup)
        conversation_manager = services_manager.conversation_file_service_manager

        test_date = datetime(2025, 11, 25)

        # Save conversation with specific date
        filename = await conversation_manager.save_conversation(
            conversation_data=test_data["conversation_data"],
            discord_user_id=test_data["discord_user_id"],
            guild_id=test_data["guild_id"],
            thread_id=test_data["thread_id"],
            date=test_date,
        )

        # Verify filename format: yyyy-mm-dd_conversation-in-{guild_id}_uuid-{thread_id}.json
        assert (
            filename
            == f"2025-11-25_conversation-in-{test_data['guild_id']}_uuid-{test_data['thread_id']}.json"
        )
