"""
Unit tests for Chatbot SQL Manager Service.

Tests cover CRUD operations for conversations including:
- Insert operations
- Delete operations (single and bulk)
- Update operations
- Query operations (by ID, user, guild, message)
- Validation and error handling
"""

import os

import pytest

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.services.chatbot_sql_manager.manager import ChatbotSQLManagerService
from source.services.constructor import construct_services_manager
from source.utils import generate_16_char_uuid


@pytest.mark.unit
class TestChatbotSQLManagerService:
    """Test Chatbot SQL Manager Service CRUD operations."""

    @pytest.fixture
    async def services_and_db(self, tmp_path, shared_test_log_file):
        """Setup services and database for testing."""
        from source.context import Context

        # Create context
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
            log_file=shared_test_log_file,
            use_timestamp_logs=False,
        )
        await services_manager.initialize_all()

        yield services_manager, servers_manager

        # Cleanup
        await servers_manager.disconnect_all()

    @pytest.fixture
    def test_data(self):
        """Provide test data."""
        test_user_id = "1234567890123456"
        test_guild_id = "9876543210987654"
        test_message_id = "1111222233334444"
        conversation_id = generate_16_char_uuid()

        # Create a dummy conversation file
        conversation_file = f"assets/data/conversations/conversation_{conversation_id}.json"

        return {
            "user_id": test_user_id,
            "guild_id": test_guild_id,
            "message_id": test_message_id,
            "conversation_id": conversation_id,
            "conversation_file": conversation_file,
        }

    @pytest.fixture
    async def chatbot_service(self, services_and_db):
        """Get the chatbot SQL manager service."""
        services_manager, servers_manager = services_and_db

        # Create ChatbotSQLManagerService instance

        chatbot_service = ChatbotSQLManagerService(services_manager.context)
        await chatbot_service.on_start(services_manager)

        yield chatbot_service, servers_manager

        # Cleanup - delete all test conversations
        from sqlalchemy import delete

        from source.server.sql_models import ConversationsModel

        db_service = servers_manager.sql_client
        delete_stmt = delete(ConversationsModel)
        await db_service.execute(delete_stmt)

    # ========================================================================
    # TEST 1: Insert Conversation
    # ========================================================================

    @pytest.mark.asyncio
    async def test_insert_conversation(self, chatbot_service, test_data):
        """Test inserting a new conversation."""
        chatbot_sql_service, servers_manager = chatbot_service

        conversation_id = await chatbot_sql_service.insert_conversation(
            conversation_file=test_data["conversation_file"],
            discord_guild_id=test_data["guild_id"],
            discord_message_id=test_data["message_id"],
            requesting_user_id=test_data["user_id"],
        )

        assert conversation_id is not None
        assert isinstance(conversation_id, str)
        assert len(conversation_id) == 16

    @pytest.mark.asyncio
    async def test_insert_conversation_empty_file(self, chatbot_service, test_data):
        """Test inserting a conversation with empty file path fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="conversation_file cannot be empty"):
            await chatbot_sql_service.insert_conversation(
                conversation_file="",
                discord_guild_id=test_data["guild_id"],
                discord_message_id=test_data["message_id"],
                requesting_user_id=test_data["user_id"],
            )

    @pytest.mark.asyncio
    async def test_insert_conversation_invalid_guild_id(self, chatbot_service, test_data):
        """Test inserting a conversation with invalid guild ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="discord_guild_id must be at least"):
            await chatbot_sql_service.insert_conversation(
                conversation_file=test_data["conversation_file"],
                discord_guild_id="123",  # Too short
                discord_message_id=test_data["message_id"],
                requesting_user_id=test_data["user_id"],
            )

    @pytest.mark.asyncio
    async def test_insert_conversation_invalid_message_id(self, chatbot_service, test_data):
        """Test inserting a conversation with invalid message ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="discord_message_id must be at least"):
            await chatbot_sql_service.insert_conversation(
                conversation_file=test_data["conversation_file"],
                discord_guild_id=test_data["guild_id"],
                discord_message_id="123",  # Too short
                requesting_user_id=test_data["user_id"],
            )

    @pytest.mark.asyncio
    async def test_insert_conversation_invalid_user_id(self, chatbot_service, test_data):
        """Test inserting a conversation with invalid user ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="requesting_user_id must be at least"):
            await chatbot_sql_service.insert_conversation(
                conversation_file=test_data["conversation_file"],
                discord_guild_id=test_data["guild_id"],
                discord_message_id=test_data["message_id"],
                requesting_user_id="123",  # Too short
            )

    # ========================================================================
    # TEST 2: Get Conversation
    # ========================================================================

    @pytest.mark.asyncio
    async def test_get_conversation(self, chatbot_service, test_data):
        """Test retrieving a conversation by ID."""
        chatbot_sql_service, _ = chatbot_service

        # Insert a conversation first
        conversation_id = await chatbot_sql_service.insert_conversation(
            conversation_file=test_data["conversation_file"],
            discord_guild_id=test_data["guild_id"],
            discord_message_id=test_data["message_id"],
            requesting_user_id=test_data["user_id"],
        )

        # Retrieve it
        conversation = await chatbot_sql_service.get_conversation(conversation_id)

        assert conversation is not None
        assert conversation["id"] == conversation_id
        assert conversation["conversation_file"] == test_data["conversation_file"]
        assert conversation["discord_guild_id"] == test_data["guild_id"]
        assert conversation["discord_message_id"] == test_data["message_id"]
        assert conversation["requesting_user_id"] == test_data["user_id"]
        assert "created_at" in conversation
        assert "updated_at" in conversation

    @pytest.mark.asyncio
    async def test_get_conversation_not_found(self, chatbot_service):
        """Test retrieving a non-existent conversation raises error."""
        chatbot_sql_service, _ = chatbot_service

        fake_id = generate_16_char_uuid()

        with pytest.raises(ValueError, match=f"Conversation with ID {fake_id} not found"):
            await chatbot_sql_service.get_conversation(fake_id)

    @pytest.mark.asyncio
    async def test_get_conversation_invalid_id(self, chatbot_service):
        """Test retrieving a conversation with invalid ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="conversation_id must be 16 characters long"):
            await chatbot_sql_service.get_conversation("short")

    # ========================================================================
    # TEST 3: Update Conversation
    # ========================================================================

    @pytest.mark.asyncio
    async def test_update_conversation_file(self, chatbot_service, test_data):
        """Test updating conversation file path."""
        chatbot_sql_service, _ = chatbot_service

        # Insert a conversation
        conversation_id = await chatbot_sql_service.insert_conversation(
            conversation_file=test_data["conversation_file"],
            discord_guild_id=test_data["guild_id"],
            discord_message_id=test_data["message_id"],
            requesting_user_id=test_data["user_id"],
        )

        # Update the file path
        new_file = "assets/data/conversations/updated_conversation.json"
        await chatbot_sql_service.update_conversation(
            conversation_id=conversation_id, conversation_file=new_file
        )

        # Verify update
        conversation = await chatbot_sql_service.get_conversation(conversation_id)
        assert conversation["conversation_file"] == new_file

    @pytest.mark.asyncio
    async def test_update_conversation_multiple_fields(self, chatbot_service, test_data):
        """Test updating multiple fields at once."""
        chatbot_sql_service, _ = chatbot_service

        # Insert a conversation
        conversation_id = await chatbot_sql_service.insert_conversation(
            conversation_file=test_data["conversation_file"],
            discord_guild_id=test_data["guild_id"],
            discord_message_id=test_data["message_id"],
            requesting_user_id=test_data["user_id"],
        )

        # Update multiple fields
        new_file = "assets/data/conversations/updated.json"
        new_guild = "5555666677778888"
        new_message = "9999888877776666"

        await chatbot_sql_service.update_conversation(
            conversation_id=conversation_id,
            conversation_file=new_file,
            discord_guild_id=new_guild,
            discord_message_id=new_message,
        )

        # Verify updates
        conversation = await chatbot_sql_service.get_conversation(conversation_id)
        assert conversation["conversation_file"] == new_file
        assert conversation["discord_guild_id"] == new_guild
        assert conversation["discord_message_id"] == new_message
        assert conversation["requesting_user_id"] == test_data["user_id"]  # Unchanged

    @pytest.mark.asyncio
    async def test_update_conversation_invalid_id(self, chatbot_service):
        """Test updating with invalid conversation ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="conversation_id must be 16 characters long"):
            await chatbot_sql_service.update_conversation(
                conversation_id="short", conversation_file="test.json"
            )

    @pytest.mark.asyncio
    async def test_update_conversation_empty_file(self, chatbot_service, test_data):
        """Test updating with empty file path fails."""
        chatbot_sql_service, _ = chatbot_service

        # Insert a conversation
        conversation_id = await chatbot_sql_service.insert_conversation(
            conversation_file=test_data["conversation_file"],
            discord_guild_id=test_data["guild_id"],
            discord_message_id=test_data["message_id"],
            requesting_user_id=test_data["user_id"],
        )

        with pytest.raises(ValueError, match="conversation_file cannot be empty"):
            await chatbot_sql_service.update_conversation(
                conversation_id=conversation_id, conversation_file=""
            )

    # ========================================================================
    # TEST 4: Delete Conversation
    # ========================================================================

    @pytest.mark.asyncio
    async def test_delete_conversation(self, chatbot_service, test_data):
        """Test deleting a conversation."""
        chatbot_sql_service, _ = chatbot_service

        # Insert a conversation
        conversation_id = await chatbot_sql_service.insert_conversation(
            conversation_file=test_data["conversation_file"],
            discord_guild_id=test_data["guild_id"],
            discord_message_id=test_data["message_id"],
            requesting_user_id=test_data["user_id"],
        )

        # Delete it
        await chatbot_sql_service.delete_conversation(conversation_id)

        # Verify deletion
        with pytest.raises(ValueError, match=f"Conversation with ID {conversation_id} not found"):
            await chatbot_sql_service.get_conversation(conversation_id)

    @pytest.mark.asyncio
    async def test_delete_conversation_invalid_id(self, chatbot_service):
        """Test deleting with invalid conversation ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="conversation_id must be 16 characters long"):
            await chatbot_sql_service.delete_conversation("short")

    @pytest.mark.asyncio
    async def test_delete_conversations_bulk(self, chatbot_service, test_data):
        """Test deleting multiple conversations at once."""
        chatbot_sql_service, _ = chatbot_service

        # Insert multiple conversations
        conversation_ids = []
        for i in range(3):
            conversation_id = await chatbot_sql_service.insert_conversation(
                conversation_file=f"assets/data/conversations/conv_{i}.json",
                discord_guild_id=test_data["guild_id"],
                discord_message_id=f"{test_data['message_id']}{i}",
                requesting_user_id=test_data["user_id"],
            )
            conversation_ids.append(conversation_id)

        # Bulk delete
        await chatbot_sql_service.delete_conversations(conversation_ids)

        # Verify all deleted
        for conv_id in conversation_ids:
            with pytest.raises(ValueError, match=f"Conversation with ID {conv_id} not found"):
                await chatbot_sql_service.get_conversation(conv_id)

    @pytest.mark.asyncio
    async def test_delete_conversations_invalid_id_in_list(self, chatbot_service):
        """Test bulk delete with invalid ID in list fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="All conversation_ids must be 16 characters long"):
            await chatbot_sql_service.delete_conversations(
                [generate_16_char_uuid(), "short", generate_16_char_uuid()]
            )

    # ========================================================================
    # TEST 5: Query Conversations by User
    # ========================================================================

    @pytest.mark.asyncio
    async def test_get_conversations_by_user(self, chatbot_service, test_data):
        """Test retrieving all conversations for a specific user."""
        chatbot_sql_service, _ = chatbot_service

        user_1 = test_data["user_id"]
        user_2 = "9999888877776666"

        # Insert conversations for user_1
        conv_ids_user1 = []
        for i in range(3):
            conv_id = await chatbot_sql_service.insert_conversation(
                conversation_file=f"assets/data/conversations/user1_conv_{i}.json",
                discord_guild_id=test_data["guild_id"],
                discord_message_id=f"{test_data['message_id']}{i}",
                requesting_user_id=user_1,
            )
            conv_ids_user1.append(conv_id)

        # Insert conversation for user_2
        await chatbot_sql_service.insert_conversation(
            conversation_file="assets/data/conversations/user2_conv.json",
            discord_guild_id=test_data["guild_id"],
            discord_message_id="5555666677778888",
            requesting_user_id=user_2,
        )

        # Query conversations for user_1
        conversations = await chatbot_sql_service.get_conversations_by_user(user_1)

        assert len(conversations) == 3
        assert all(conv["requesting_user_id"] == user_1 for conv in conversations)
        assert set(conv["id"] for conv in conversations) is set(conv_ids_user1)

    @pytest.mark.asyncio
    async def test_get_conversations_by_user_no_results(self, chatbot_service):
        """Test retrieving conversations for user with no conversations returns empty list."""
        chatbot_sql_service, _ = chatbot_service

        conversations = await chatbot_sql_service.get_conversations_by_user("1111222233334444")

        assert conversations == []

    @pytest.mark.asyncio
    async def test_get_conversations_by_user_invalid_id(self, chatbot_service):
        """Test querying with invalid user ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="requesting_user_id must be at least"):
            await chatbot_sql_service.get_conversations_by_user("123")

    # ========================================================================
    # TEST 6: Query Conversations by Guild
    # ========================================================================

    @pytest.mark.asyncio
    async def test_get_conversations_by_guild(self, chatbot_service, test_data):
        """Test retrieving all conversations for a specific guild."""
        chatbot_sql_service, _ = chatbot_service

        guild_1 = test_data["guild_id"]
        guild_2 = "5555444433332222"

        # Insert conversations for guild_1
        conv_ids_guild1 = []
        for i in range(3):
            conv_id = await chatbot_sql_service.insert_conversation(
                conversation_file=f"assets/data/conversations/guild1_conv_{i}.json",
                discord_guild_id=guild_1,
                discord_message_id=f"{test_data['message_id']}{i}",
                requesting_user_id=test_data["user_id"],
            )
            conv_ids_guild1.append(conv_id)

        # Insert conversation for guild_2
        await chatbot_sql_service.insert_conversation(
            conversation_file="assets/data/conversations/guild2_conv.json",
            discord_guild_id=guild_2,
            discord_message_id="6666777788889999",
            requesting_user_id=test_data["user_id"],
        )

        # Query conversations for guild_1
        conversations = await chatbot_sql_service.get_conversations_by_guild(guild_1)

        assert len(conversations) == 3
        assert all(conv["discord_guild_id"] == guild_1 for conv in conversations)
        assert set(conv["id"] for conv in conversations) is set(conv_ids_guild1)

    @pytest.mark.asyncio
    async def test_get_conversations_by_guild_no_results(self, chatbot_service):
        """Test retrieving conversations for guild with no conversations returns empty list."""
        chatbot_sql_service, _ = chatbot_service

        conversations = await chatbot_sql_service.get_conversations_by_guild("9999888877776666")

        assert conversations == []

    @pytest.mark.asyncio
    async def test_get_conversations_by_guild_invalid_id(self, chatbot_service):
        """Test querying with invalid guild ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="discord_guild_id must be at least"):
            await chatbot_sql_service.get_conversations_by_guild("123")

    # ========================================================================
    # TEST 7: Query Conversation by Message ID
    # ========================================================================

    @pytest.mark.asyncio
    async def test_get_conversation_by_message_id(self, chatbot_service, test_data):
        """Test retrieving a conversation by Discord message ID."""
        chatbot_sql_service, _ = chatbot_service

        # Insert a conversation
        conversation_id = await chatbot_sql_service.insert_conversation(
            conversation_file=test_data["conversation_file"],
            discord_guild_id=test_data["guild_id"],
            discord_message_id=test_data["message_id"],
            requesting_user_id=test_data["user_id"],
        )

        # Retrieve by message ID
        conversation = await chatbot_sql_service.get_conversation_by_message_id(
            test_data["message_id"]
        )

        assert conversation is not None
        assert conversation["id"] == conversation_id
        assert conversation["discord_message_id"] == test_data["message_id"]

    @pytest.mark.asyncio
    async def test_get_conversation_by_message_id_not_found(self, chatbot_service):
        """Test retrieving conversation by non-existent message ID raises error."""
        chatbot_sql_service, _ = chatbot_service

        fake_message_id = "9999888877776666"

        with pytest.raises(ValueError, match=f"Conversation with message ID {fake_message_id}"):
            await chatbot_sql_service.get_conversation_by_message_id(fake_message_id)

    @pytest.mark.asyncio
    async def test_get_conversation_by_message_id_invalid_id(self, chatbot_service):
        """Test querying with invalid message ID fails."""
        chatbot_sql_service, _ = chatbot_service

        with pytest.raises(ValueError, match="discord_message_id must be at least"):
            await chatbot_sql_service.get_conversation_by_message_id("123")

    # ========================================================================
    # TEST 8: Service Lifecycle
    # ========================================================================

    @pytest.mark.asyncio
    async def test_service_initialization(self, services_and_db):
        """Test service initializes correctly."""
        services_manager, servers_manager = services_and_db

        chatbot_service = ChatbotSQLManagerService(services_manager.context)
        result = await chatbot_service.on_start(services_manager)

        assert result is True
        assert chatbot_service.services is not None

    @pytest.mark.asyncio
    async def test_service_close(self, chatbot_service):
        """Test service closes correctly."""
        chatbot_sql_service, _ = chatbot_service

        result = await chatbot_sql_service.on_close()

        assert result is True
