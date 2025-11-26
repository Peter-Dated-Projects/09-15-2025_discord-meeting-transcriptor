"""
Quick database schema fix script.

This script:
1. Adds missing discord_thread_id column to conversations table
2. Creates conversations_store table if it doesn't exist
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import aiomysql
from dotenv import load_dotenv

# Load environment variables
load_dotenv(".env.local")


async def fix_schema():
    """Fix database schema issues."""
    
    # Get database credentials
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DB", "mysql")
    
    print(f"Connecting to MySQL at {host}:{port}, database: {database}")
    
    try:
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
                # Fix 1: Check and add discord_thread_id to conversations table
                print("\n--- Checking conversations table ---")
                
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = 'conversations' "
                    "AND column_name = 'discord_thread_id'",
                    (database,)
                )
                result = await cursor.fetchone()
                
                if result[0] == 0:
                    print("⚠ Adding missing discord_thread_id column...")
                    await cursor.execute(
                        "ALTER TABLE conversations "
                        "ADD COLUMN discord_thread_id VARCHAR(20) NOT NULL, "
                        "ADD INDEX idx_discord_thread_id (discord_thread_id)"
                    )
                    await conn.commit()
                    print("✅ Added discord_thread_id column")
                else:
                    print("✓ discord_thread_id column exists")
                
                # Fix 2: Check and create conversations_store table
                print("\n--- Checking conversations_store table ---")
                
                await cursor.execute(
                    "SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = 'conversations_store'",
                    (database,)
                )
                result = await cursor.fetchone()
                
                if result[0] == 0:
                    print("⚠ Creating conversations_store table...")
                    create_table_sql = """
                    CREATE TABLE conversations_store (
                        id VARCHAR(16) PRIMARY KEY,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        session_id VARCHAR(16) NOT NULL,
                        filename VARCHAR(512) NOT NULL,
                        INDEX idx_session_id (session_id),
                        INDEX idx_filename (filename),
                        CONSTRAINT fk_conversations_store_session_id 
                            FOREIGN KEY (session_id) 
                            REFERENCES conversations(id)
                            ON DELETE CASCADE
                    )
                    """
                    await cursor.execute(create_table_sql)
                    await conn.commit()
                    print("✅ Created conversations_store table")
                else:
                    print("✓ conversations_store table exists")
                
                # Verify foreign key
                print("\n--- Verifying foreign key constraint ---")
                await cursor.execute(
                    "SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'conversations_store' "
                    "AND CONSTRAINT_TYPE = 'FOREIGN KEY'",
                    (database,)
                )
                fk_result = await cursor.fetchall()
                
                if fk_result:
                    print(f"✓ Foreign key constraint exists: {fk_result[0][0]}")
                else:
                    print("⚠ No foreign key constraint found")
                
        pool.close()
        await pool.wait_closed()
        
        print("\n" + "=" * 70)
        print("✅ Schema fixes complete!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print("=" * 70)
    print("Database Schema Fix Script")
    print("=" * 70)
    
    asyncio.run(fix_schema())
