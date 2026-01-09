"""
Migration script to add monitoring_stopped column to conversations table.

This script adds the monitoring_stopped column (INTEGER default 0) to the
conversations table if it doesn't exist.

Note: This script uses the application's Context and SQL client for database access,
ensuring it uses the same configuration as the running bot.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from source.context import Context
from source.server.constructor import ServerManagerType, construct_server_manager


async def migrate_conversations_table():
    """Add monitoring_stopped column to conversations table if it doesn't exist."""

    print("Initializing database connection...")

    # Initialize Context and Server Manager (same as the bot does)
    context = Context()
    servers_manager = construct_server_manager(ServerManagerType.DEVELOPMENT, context)
    context.set_server_manager(servers_manager)
    await servers_manager.connect_all()

    sql_client = servers_manager.sql_client
    print(f"✓ Connected to database")

    sql_client = servers_manager.sql_client
    print(f"✓ Connected to database")

    try:
        # Check if table exists
        query = text("""
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
            AND table_name = 'conversations'
        """)
        result = await sql_client.execute(query)

        if not result or result[0]["count"] == 0:
            print("❌ Table 'conversations' does not exist!")
            print("   Run the application first to create the table.")
            return

        print("✓ Table 'conversations' exists")

        # Check if monitoring_stopped column exists
        query = text("""
            SELECT COUNT(*) as count
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
            AND table_name = 'conversations'
            AND column_name = 'monitoring_stopped'
        """)
        result = await sql_client.execute(query)

        if result and result[0]["count"] > 0:
            print("✓ Column 'monitoring_stopped' already exists in conversations table")
            print("   No migration needed!")
            return

        print("⚠ Column 'monitoring_stopped' is MISSING from conversations table")
        print("  Adding column...")

        # Add the monitoring_stopped column with default value of 0
        alter_query = text(
            "ALTER TABLE conversations ADD COLUMN monitoring_stopped INT NOT NULL DEFAULT 0"
        )
        await sql_client.execute(alter_query)

        print("✅ Successfully added 'monitoring_stopped' column to conversations table")

        # Verify the column was added
        result = await sql_client.execute(
            text("""
            SELECT COUNT(*) as count
            FROM information_schema.columns
            WHERE table_schema = DATABASE()
            AND table_name = 'conversations'
            AND column_name = 'monitoring_stopped'
        """)
        )

        if result and result[0]["count"] > 0:
            print("✓ Verification: Column 'monitoring_stopped' exists")
        else:
            print("❌ Verification failed: Column 'monitoring_stopped' not found")

    except Exception as e:
        print(f"❌ Error during migration: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Clean up
        await servers_manager.disconnect_all()


if __name__ == "__main__":
    print("=" * 70)
    print("MIGRATION: Add monitoring_stopped column to conversations table")
    print("=" * 70)
    print()

    asyncio.run(migrate_conversations_table())

    print()
    print("=" * 70)
    print("Migration complete!")
    print("=" * 70)
