"""
Migration script to add the echo_channels table to the database.

This script creates the echo_channels table for tracking which channels
have echo bot interaction enabled.

Run this script once to add the table to existing databases.
New databases will have the table created automatically.

Usage:
    python scripts/add_echo_channels_table.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from sqlalchemy import text

# Load environment variables
load_dotenv(dotenv_path=".env.local")
load_dotenv()


async def create_echo_channels_table():
    """Create the echo_channels table if it doesn't exist."""
    from source.server.constructor import construct_server_manager
    from source.constructor import ServerManagerType

    # Determine server type from environment
    env = os.getenv("ENVIRONMENT", "development").lower()
    if env == "production":
        server_type = ServerManagerType.PRODUCTION
    else:
        server_type = ServerManagerType.DEVELOPMENT

    print(f"Running migration for {env} environment...")

    # Create server manager to get database connection
    server_manager = construct_server_manager(server_type)
    await server_manager.on_start()

    try:
        # Check if table exists
        check_table_sql = """
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name='echo_channels';
        """

        result = await server_manager.sql_client.execute(text(check_table_sql))

        if result:
            print("Table 'echo_channels' already exists. No migration needed.")
            return

        # Create the table
        create_table_sql = """
        CREATE TABLE echo_channels (
            channel_id VARCHAR(20) PRIMARY KEY,
            guild_id VARCHAR(20) NOT NULL,
            enabled_at DATETIME NOT NULL
        );
        """

        await server_manager.sql_client.execute(text(create_table_sql))
        print("Successfully created 'echo_channels' table.")

        # Create index on guild_id for faster lookups
        create_index_sql = """
        CREATE INDEX ix_echo_channels_guild_id ON echo_channels (guild_id);
        """

        await server_manager.sql_client.execute(text(create_index_sql))
        print("Successfully created index on guild_id.")

        print("\nMigration completed successfully!")

    except Exception as e:
        print(f"Error during migration: {e}")
        raise
    finally:
        await server_manager.on_close()


if __name__ == "__main__":
    asyncio.run(create_echo_channels_table())
