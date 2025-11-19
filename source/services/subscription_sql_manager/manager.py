from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select, update

if TYPE_CHECKING:
    from source.context import Context

from source.server.sql_models import SubscriptionsModel, SubscriptionType
from source.services.manager import Manager
from source.utils import get_current_timestamp_est

# -------------------------------------------------------------- #
# Subscription SQL Manager Service
# -------------------------------------------------------------- #


class SubscriptionSQLManagerService(Manager):
    """Service for managing guild subscription SQL operations."""

    def __init__(self, context: "Context"):
        super().__init__(context)

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    async def on_start(self, services):
        await super().on_start(services)
        await self.services.logging_service.info("SubscriptionSQLManagerService initialized")
        return True

    async def on_close(self):
        await self.services.logging_service.info("SubscriptionSQLManagerService closed")
        return True

    # -------------------------------------------------------------- #
    # Subscription CRUD Methods
    # -------------------------------------------------------------- #

    async def insert_subscription(
        self,
        discord_server_id: str,
        chroma_collection_name: str,
        subscription_type: SubscriptionType = SubscriptionType.FREE,
        activated_guild_at: datetime | None = None,
    ) -> None:
        """
        Insert a new guild subscription entry.

        Args:
            discord_server_id: Discord Guild (Server) ID
            chroma_collection_name: Name of the Chroma collection for this guild
            subscription_type: Type of subscription (FREE or PAID), defaults to FREE
            activated_guild_at: Timestamp when subscription was activated (optional)

        Raises:
            ValueError: If discord_server_id is invalid or subscription already exists
        """
        # Validate inputs
        if not discord_server_id or len(discord_server_id) < 17:
            raise ValueError("discord_server_id must be at least 17 characters long")
        if not chroma_collection_name:
            raise ValueError("chroma_collection_name cannot be empty")
        if not isinstance(subscription_type, SubscriptionType):
            raise ValueError("subscription_type must be a valid SubscriptionType enum value")

        # Get current timestamp
        joined_at = get_current_timestamp_est()

        # Prepare subscription data
        subscription_data = {
            "discord_server_id": discord_server_id,
            "chroma_collection_name": chroma_collection_name,
            "joined_guild_at": joined_at,
            "activated_guild_at": activated_guild_at,
            "subscription_type": subscription_type.value,
        }

        # Build and execute insert statement
        stmt = insert(SubscriptionsModel).values(**subscription_data)
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Inserted subscription for guild: {discord_server_id} with type: {subscription_type.value}"
        )

    async def delete_subscription(self, discord_server_id: str) -> None:
        """
        Delete a guild subscription entry by its Discord server ID.

        Args:
            discord_server_id: Discord Guild (Server) ID to delete

        Raises:
            ValueError: If discord_server_id is invalid
        """
        # Validate input
        if not discord_server_id or len(discord_server_id) < 17:
            raise ValueError("discord_server_id must be at least 17 characters long")

        # Build delete query
        query = delete(SubscriptionsModel).where(
            SubscriptionsModel.discord_server_id == discord_server_id
        )

        # Execute delete
        await self.server.sql_client.execute(query)
        await self.services.logging_service.info(
            f"Deleted subscription for guild: {discord_server_id}"
        )

    async def search_subscription(self, discord_server_id: str) -> SubscriptionsModel | None:
        """
        Search for a guild subscription entry by Discord server ID.

        Args:
            discord_server_id: Discord Guild (Server) ID to search for

        Returns:
            SubscriptionsModel if found, None otherwise

        Raises:
            ValueError: If discord_server_id is invalid
        """
        # Validate input
        if not discord_server_id or len(discord_server_id) < 17:
            raise ValueError("discord_server_id must be at least 17 characters long")

        # Build select query
        query = select(SubscriptionsModel).where(
            SubscriptionsModel.discord_server_id == discord_server_id
        )

        # Execute query
        result = await self.server.sql_client.execute(query)
        subscription = result.scalars().first()

        if subscription:
            await self.services.logging_service.debug(
                f"Found subscription for guild: {discord_server_id}"
            )
        else:
            await self.services.logging_service.debug(
                f"No subscription found for guild: {discord_server_id}"
            )

        return subscription

    async def update_subscription(
        self,
        discord_server_id: str,
        chroma_collection_name: str | None = None,
        activated_guild_at: datetime | None = None,
        subscription_type: SubscriptionType | None = None,
    ) -> None:
        """
        Update a guild subscription entry.

        Args:
            discord_server_id: Discord Guild (Server) ID to update
            chroma_collection_name: New Chroma collection name (optional)
            activated_guild_at: New activation timestamp (optional)
            subscription_type: New subscription type (optional)

        Raises:
            ValueError: If discord_server_id is invalid or no update fields provided
        """
        # Validate input
        if not discord_server_id or len(discord_server_id) < 17:
            raise ValueError("discord_server_id must be at least 17 characters long")

        # Build update dict with only provided values
        update_dict = {}
        if chroma_collection_name is not None:
            update_dict["chroma_collection_name"] = chroma_collection_name
        if activated_guild_at is not None:
            update_dict["activated_guild_at"] = activated_guild_at
        if subscription_type is not None:
            if not isinstance(subscription_type, SubscriptionType):
                raise ValueError("subscription_type must be a valid SubscriptionType enum value")
            update_dict["subscription_type"] = subscription_type.value

        # Ensure at least one field is being updated
        if not update_dict:
            raise ValueError("At least one field must be provided for update")

        # Build update query
        stmt = (
            update(SubscriptionsModel)
            .where(SubscriptionsModel.discord_server_id == discord_server_id)
            .values(**update_dict)
        )

        # Execute update
        await self.server.sql_client.execute(stmt)
        await self.services.logging_service.info(
            f"Updated subscription for guild: {discord_server_id} with fields: {list(update_dict.keys())}"
        )

    async def list_all_subscriptions(self) -> list[SubscriptionsModel]:
        """
        Retrieve all guild subscription entries.

        Returns:
            List of all SubscriptionsModel entries
        """
        # Build select query
        query = select(SubscriptionsModel)

        # Execute query
        result = await self.server.sql_client.execute(query)
        subscriptions = result.scalars().all()

        await self.services.logging_service.debug(f"Retrieved {len(subscriptions)} subscriptions")
        return list(subscriptions)

    async def search_subscriptions_by_type(
        self, subscription_type: SubscriptionType
    ) -> list[SubscriptionsModel]:
        """
        Search for guild subscriptions by subscription type.

        Args:
            subscription_type: Type of subscription to filter by (FREE or PAID)

        Returns:
            List of SubscriptionsModel entries matching the subscription type

        Raises:
            ValueError: If subscription_type is invalid
        """
        # Validate input
        if not isinstance(subscription_type, SubscriptionType):
            raise ValueError("subscription_type must be a valid SubscriptionType enum value")

        # Build select query
        query = select(SubscriptionsModel).where(
            SubscriptionsModel.subscription_type == subscription_type.value
        )

        # Execute query
        result = await self.server.sql_client.execute(query)
        subscriptions = result.scalars().all()

        await self.services.logging_service.debug(
            f"Found {len(subscriptions)} subscriptions with type: {subscription_type.value}"
        )
        return list(subscriptions)
