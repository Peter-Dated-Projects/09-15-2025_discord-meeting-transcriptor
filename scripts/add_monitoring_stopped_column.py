"""
Migration script to add monitoring_stopped column to conversations table.

This script adds the monitoring_stopped column (INTEGER default 0) to the
conversations table if it doesn't exist.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiomysql
from dotenv import load_dotenv

# Load environment variables
load_dotenv(".env.local")


async def migrate_conversations_table():
    """Add monitoring_stopped column to conversations table if it doesn't exist."""

    # Get database credentials from environment
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DB", "mysql")

    print(f"Connecting to MySQL at {host}:{port}, database: {database}")

    try:
        # Create connection pool
        pool = await aiomysql.create_pool(
            host=host,
            port=port,
            user=user,
            password=password,
            db=database,
            minsize=1,
            maxsize=1,
        )

        async with pool.acquire() as conn:
            async with conn.cursor() as cursor:
                # Check if table exists
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = 'conversations'",
                    (database,),
                )
                result = await cursor.fetchone()

                if result[0] == 0:
                    print("❌ Table 'conversations' does not exist!")
                    print("   Run the application first to create the table.")
                    return

                print("✓ Table 'conversations' exists")

                # Check if monitoring_stopped column exists
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'conversations' "
                    "AND column_name = 'monitoring_stopped'",
                    (database,),
                )
                result = await cursor.fetchone()

                if result[0] > 0:
                    print("✓ Column 'monitoring_stopped' already exists in conversations table")
                    print("   No migration needed!")
                    return

                print("⚠ Column 'monitoring_stopped' is MISSING from conversations table")
                print("  Adding column...")

                # Add the monitoring_stopped column with default value of 0
                await cursor.execute(
                    "ALTER TABLE conversations ADD COLUMN monitoring_stopped INT NOT NULL DEFAULT 0"
                )
                await conn.commit()

                print("✅ Successfully added 'monitoring_stopped' column to conversations table")

                # Verify the column was added
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'conversations' "
                    "AND column_name = 'monitoring_stopped'",
                    (database,),
                )
                result = await cursor.fetchone()

                if result[0] > 0:
                    print("✓ Verification: Column 'monitoring_stopped' exists")
                else:
                    print("❌ Verification failed: Column 'monitoring_stopped' not found")

        pool.close()
        await pool.wait_closed()

    except Exception as e:
        print(f"❌ Error during migration: {e}")
        import traceback

        traceback.print_exc()


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
