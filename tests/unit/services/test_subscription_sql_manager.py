"""
Unit tests for Subscription SQL Manager Service.

Tests cover CRUD operations for guild subscriptions including:
- Insert new subscription
- Search for subscription
- Update subscription details
- Delete subscription
- List all subscriptions
- Filter subscriptions by type
"""

import os
from datetime import datetime

import pytest

from source.constructor import ServerManagerType
from source.server.constructor import construct_server_manager
from source.server.sql_models import SubscriptionType, SubscriptionsModel
from source.services.constructor import construct_services_manager
from source.services.subscription_sql_manager.manager import SubscriptionSQLManagerService
from source.utils import get_current_timestamp_est


@pytest.mark.unit
class TestSubscriptionSQLManagerService:
    """Test Subscription SQL Manager Service CRUD operations."""

    @pytest.fixture
    async def services_and_db(self, tmp_path):
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

        services_manager = construct_services_manager(
            ServerManagerType.DEVELOPMENT,
            context=context,
            storage_path=storage_path,
            recording_storage_path=recording_storage_path,
            transcription_storage_path=transcription_storage_path,
        )
        await services_manager.initialize_all()

        yield services_manager, servers_manager

        # Cleanup
        await servers_manager.disconnect_all()

    @pytest.fixture
    def test_data(self):
        """Provide test data for subscriptions."""
        return {
            "guild_id_1": "123456789012345678",
            "guild_id_2": "987654321098765432",
            "guild_id_3": "555555555555555555",
            "collection_name_1": "test_collection_guild_1",
            "collection_name_2": "test_collection_guild_2",
            "collection_name_3": "test_collection_guild_3",
        }

    @pytest.fixture
    async def setup_subscription_service(self, services_and_db):
        """Setup subscription SQL service with cleanup."""
        services_manager, servers_manager = services_and_db
        
        # Get the subscription service from the services manager
        subscription_service = services_manager.subscription_sql_manager

        yield subscription_service, servers_manager

        # Cleanup - delete all test subscriptions
        from sqlalchemy import delete
        db_service = servers_manager.sql_client
        
        delete_stmt = delete(SubscriptionsModel)
        await db_service.execute(delete_stmt)

    # ========================================================================
    # TEST 1: Insert Subscription
    # ========================================================================

    @pytest.mark.asyncio
    async def test_insert_subscription_free(self, setup_subscription_service, test_data):
        """Test inserting a new FREE subscription."""
        subscription_service, servers_manager = setup_subscription_service

        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
            subscription_type=SubscriptionType.FREE,
        )

        # Verify the subscription was inserted
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription is not None
        assert subscription.discord_server_id == test_data["guild_id_1"]
        assert subscription.chroma_collection_name == test_data["collection_name_1"]
        assert subscription.subscription_type == SubscriptionType.FREE.value
        assert subscription.joined_guild_at is not None
        assert subscription.activated_guild_at is None

    @pytest.mark.asyncio
    async def test_insert_subscription_paid_with_activation(
        self, setup_subscription_service, test_data
    ):
        """Test inserting a new PAID subscription with activation timestamp."""
        subscription_service, servers_manager = setup_subscription_service

        activation_time = get_current_timestamp_est()

        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_2"],
            chroma_collection_name=test_data["collection_name_2"],
            subscription_type=SubscriptionType.PAID,
            activated_guild_at=activation_time,
        )

        # Verify the subscription was inserted
        subscription = await subscription_service.search_subscription(test_data["guild_id_2"])
        assert subscription is not None
        assert subscription.discord_server_id == test_data["guild_id_2"]
        assert subscription.subscription_type == SubscriptionType.PAID.value
        assert subscription.activated_guild_at is not None

    @pytest.mark.asyncio
    async def test_insert_subscription_invalid_guild_id(
        self, setup_subscription_service, test_data
    ):
        """Test that inserting with invalid guild ID raises ValueError."""
        subscription_service, _ = setup_subscription_service

        with pytest.raises(ValueError, match="discord_server_id must be at least 17 characters"):
            await subscription_service.insert_subscription(
                discord_server_id="12345",  # Too short
                chroma_collection_name=test_data["collection_name_1"],
            )

    @pytest.mark.asyncio
    async def test_insert_subscription_empty_collection_name(
        self, setup_subscription_service, test_data
    ):
        """Test that inserting with empty collection name raises ValueError."""
        subscription_service, _ = setup_subscription_service

        with pytest.raises(ValueError, match="chroma_collection_name cannot be empty"):
            await subscription_service.insert_subscription(
                discord_server_id=test_data["guild_id_1"],
                chroma_collection_name="",
            )

    # ========================================================================
    # TEST 2: Search Subscription
    # ========================================================================

    @pytest.mark.asyncio
    async def test_search_subscription_exists(self, setup_subscription_service, test_data):
        """Test searching for an existing subscription."""
        subscription_service, _ = setup_subscription_service

        # Insert a subscription first
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
        )

        # Search for it
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription is not None
        assert subscription.discord_server_id == test_data["guild_id_1"]

    @pytest.mark.asyncio
    async def test_search_subscription_not_exists(self, setup_subscription_service, test_data):
        """Test searching for a non-existent subscription returns None."""
        subscription_service, _ = setup_subscription_service

        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription is None

    @pytest.mark.asyncio
    async def test_search_subscription_invalid_guild_id(self, setup_subscription_service):
        """Test that searching with invalid guild ID raises ValueError."""
        subscription_service, _ = setup_subscription_service

        with pytest.raises(ValueError, match="discord_server_id must be at least 17 characters"):
            await subscription_service.search_subscription("12345")

    # ========================================================================
    # TEST 3: Update Subscription
    # ========================================================================

    @pytest.mark.asyncio
    async def test_update_subscription_collection_name(
        self, setup_subscription_service, test_data
    ):
        """Test updating a subscription's collection name."""
        subscription_service, _ = setup_subscription_service

        # Insert a subscription first
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
        )

        # Update the collection name
        new_collection_name = "updated_collection_name"
        await subscription_service.update_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=new_collection_name,
        )

        # Verify the update
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription.chroma_collection_name == new_collection_name

    @pytest.mark.asyncio
    async def test_update_subscription_type(self, setup_subscription_service, test_data):
        """Test updating a subscription's type from FREE to PAID."""
        subscription_service, _ = setup_subscription_service

        # Insert a FREE subscription
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
            subscription_type=SubscriptionType.FREE,
        )

        # Update to PAID
        await subscription_service.update_subscription(
            discord_server_id=test_data["guild_id_1"],
            subscription_type=SubscriptionType.PAID,
        )

        # Verify the update
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription.subscription_type == SubscriptionType.PAID.value

    @pytest.mark.asyncio
    async def test_update_subscription_activation(self, setup_subscription_service, test_data):
        """Test updating a subscription's activation timestamp."""
        subscription_service, _ = setup_subscription_service

        # Insert a subscription without activation
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
        )

        # Update with activation timestamp
        activation_time = get_current_timestamp_est()
        await subscription_service.update_subscription(
            discord_server_id=test_data["guild_id_1"],
            activated_guild_at=activation_time,
        )

        # Verify the update
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription.activated_guild_at is not None

    @pytest.mark.asyncio
    async def test_update_subscription_multiple_fields(
        self, setup_subscription_service, test_data
    ):
        """Test updating multiple fields at once."""
        subscription_service, _ = setup_subscription_service

        # Insert a subscription
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
            subscription_type=SubscriptionType.FREE,
        )

        # Update multiple fields
        new_collection_name = "new_collection"
        activation_time = get_current_timestamp_est()
        await subscription_service.update_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=new_collection_name,
            activated_guild_at=activation_time,
            subscription_type=SubscriptionType.PAID,
        )

        # Verify all updates
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription.chroma_collection_name == new_collection_name
        assert subscription.activated_guild_at is not None
        assert subscription.subscription_type == SubscriptionType.PAID.value

    @pytest.mark.asyncio
    async def test_update_subscription_no_fields(self, setup_subscription_service, test_data):
        """Test that updating with no fields raises ValueError."""
        subscription_service, _ = setup_subscription_service

        # Insert a subscription first
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
        )

        # Try to update with no fields
        with pytest.raises(ValueError, match="At least one field must be provided for update"):
            await subscription_service.update_subscription(
                discord_server_id=test_data["guild_id_1"],
            )

    # ========================================================================
    # TEST 4: Delete Subscription
    # ========================================================================

    @pytest.mark.asyncio
    async def test_delete_subscription(self, setup_subscription_service, test_data):
        """Test deleting a subscription."""
        subscription_service, _ = setup_subscription_service

        # Insert a subscription first
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
        )

        # Verify it exists
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription is not None

        # Delete it
        await subscription_service.delete_subscription(test_data["guild_id_1"])

        # Verify it's gone
        subscription = await subscription_service.search_subscription(test_data["guild_id_1"])
        assert subscription is None

    @pytest.mark.asyncio
    async def test_delete_subscription_invalid_guild_id(self, setup_subscription_service):
        """Test that deleting with invalid guild ID raises ValueError."""
        subscription_service, _ = setup_subscription_service

        with pytest.raises(ValueError, match="discord_server_id must be at least 17 characters"):
            await subscription_service.delete_subscription("12345")

    # ========================================================================
    # TEST 5: List All Subscriptions
    # ========================================================================

    @pytest.mark.asyncio
    async def test_list_all_subscriptions_empty(self, setup_subscription_service):
        """Test listing subscriptions when none exist."""
        subscription_service, _ = setup_subscription_service

        subscriptions = await subscription_service.list_all_subscriptions()
        assert isinstance(subscriptions, list)
        assert len(subscriptions) == 0

    @pytest.mark.asyncio
    async def test_list_all_subscriptions_multiple(self, setup_subscription_service, test_data):
        """Test listing all subscriptions when multiple exist."""
        subscription_service, _ = setup_subscription_service

        # Insert multiple subscriptions
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
        )
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_2"],
            chroma_collection_name=test_data["collection_name_2"],
        )
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_3"],
            chroma_collection_name=test_data["collection_name_3"],
        )

        # List all subscriptions
        subscriptions = await subscription_service.list_all_subscriptions()
        assert len(subscriptions) == 3

        # Verify all guild IDs are present
        guild_ids = {sub.discord_server_id for sub in subscriptions}
        assert test_data["guild_id_1"] in guild_ids
        assert test_data["guild_id_2"] in guild_ids
        assert test_data["guild_id_3"] in guild_ids

    # ========================================================================
    # TEST 6: Search Subscriptions by Type
    # ========================================================================

    @pytest.mark.asyncio
    async def test_search_subscriptions_by_type_free(
        self, setup_subscription_service, test_data
    ):
        """Test searching for FREE subscriptions."""
        subscription_service, _ = setup_subscription_service

        # Insert mixed subscriptions
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
            subscription_type=SubscriptionType.FREE,
        )
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_2"],
            chroma_collection_name=test_data["collection_name_2"],
            subscription_type=SubscriptionType.PAID,
        )
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_3"],
            chroma_collection_name=test_data["collection_name_3"],
            subscription_type=SubscriptionType.FREE,
        )

        # Search for FREE subscriptions
        free_subscriptions = await subscription_service.search_subscriptions_by_type(
            SubscriptionType.FREE
        )
        assert len(free_subscriptions) == 2
        assert all(sub.subscription_type == SubscriptionType.FREE.value for sub in free_subscriptions)

    @pytest.mark.asyncio
    async def test_search_subscriptions_by_type_paid(
        self, setup_subscription_service, test_data
    ):
        """Test searching for PAID subscriptions."""
        subscription_service, _ = setup_subscription_service

        # Insert mixed subscriptions
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_1"],
            chroma_collection_name=test_data["collection_name_1"],
            subscription_type=SubscriptionType.FREE,
        )
        await subscription_service.insert_subscription(
            discord_server_id=test_data["guild_id_2"],
            chroma_collection_name=test_data["collection_name_2"],
            subscription_type=SubscriptionType.PAID,
        )

        # Search for PAID subscriptions
        paid_subscriptions = await subscription_service.search_subscriptions_by_type(
            SubscriptionType.PAID
        )
        assert len(paid_subscriptions) == 1
        assert paid_subscriptions[0].subscription_type == SubscriptionType.PAID.value

    @pytest.mark.asyncio
    async def test_search_subscriptions_by_type_none_found(self, setup_subscription_service):
        """Test searching for subscriptions by type when none exist."""
        subscription_service, _ = setup_subscription_service

        # Search for PAID subscriptions when none exist
        paid_subscriptions = await subscription_service.search_subscriptions_by_type(
            SubscriptionType.PAID
        )
        assert len(paid_subscriptions) == 0

    @pytest.mark.asyncio
    async def test_search_subscriptions_by_type_invalid_type(self, setup_subscription_service):
        """Test that searching with invalid subscription type raises ValueError."""
        subscription_service, _ = setup_subscription_service

        with pytest.raises(ValueError, match="subscription_type must be a valid SubscriptionType"):
            await subscription_service.search_subscriptions_by_type("INVALID_TYPE")
