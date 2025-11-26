"""
Migration script to add missing discord_thread_id column to conversations table.

This script checks if the conversations table is missing the discord_thread_id column
and adds it if necessary.
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
    """Add discord_thread_id column to conversations table if it doesn't exist."""
    
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
                    (database,)
                )
                result = await cursor.fetchone()
                
                if result[0] == 0:
                    print("❌ Table 'conversations' does not exist!")
                    print("   Run the application first to create the table.")
                    return
                
                print("✓ Table 'conversations' exists")
                
                # Check if discord_thread_id column exists
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'conversations' "
                    "AND column_name = 'discord_thread_id'",
                    (database,)
                )
                result = await cursor.fetchone()
                
                if result[0] > 0:
                    print("✓ Column 'discord_thread_id' already exists in conversations table")
                    print("   No migration needed!")
                    return
                
                print("⚠ Column 'discord_thread_id' is MISSING from conversations table")
                print("  Adding column...")
                
                # Add the missing column
                alter_query = (
                    "ALTER TABLE conversations "
                    "ADD COLUMN discord_thread_id VARCHAR(20) NOT NULL, "
                    "ADD INDEX idx_discord_thread_id (discord_thread_id)"
                )
                
                await cursor.execute(alter_query)
                await conn.commit()
                
                print("✅ Successfully added 'discord_thread_id' column to conversations table!")
                print("   The column has been created with:")
                print("   - Type: VARCHAR(20)")
                print("   - Constraint: NOT NULL")
                print("   - Index: Added for performance")
                
        pool.close()
        await pool.wait_closed()
        
    except Exception as e:
        print(f"❌ Error during migration: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("=" * 70)
    print("Conversations Table Migration Script")
    print("=" * 70)
    print()
    
    asyncio.run(migrate_conversations_table())
    
    print()
    print("=" * 70)
    print("Migration complete!")
    print("=" * 70)
