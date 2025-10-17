"""
PostgreSQL server handler for database operations.

This module provides an object-oriented handler for managing connections
and operations with PostgreSQL database.
"""

import os
from typing import Optional, Any, Dict, List
from contextlib import asynccontextmanager
import asyncpg
from asyncpg import Pool

from .server import BaseServerHandler


# -------------------------------------------------------------- #
# PostgreSQL Server Handler
# -------------------------------------------------------------- #


class PostgreSQLServer(BaseServerHandler):
    """Handler for PostgreSQL database server operations."""

    def __init__(
        self,
        name: str = "PostgreSQL",
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        min_pool_size: int = 10,
        max_pool_size: int = 20,
    ):
        """
        Initialize PostgreSQL server handler.

        Args:
            name: Name identifier for this server instance
            host: PostgreSQL host address (default: from env POSTGRES_HOST or 'localhost')
            port: PostgreSQL port (default: from env POSTGRES_PORT or 5432)
            database: Database name (default: from env POSTGRES_DB or 'postgres')
            user: Database user (default: from env POSTGRES_USER or 'postgres')
            password: Database password (default: from env POSTGRES_PASSWORD)
            min_pool_size: Minimum number of connections in the pool
            max_pool_size: Maximum number of connections in the pool
        """
        super().__init__(name)

        # Load configuration from environment or use defaults
        self.host = host or os.getenv("POSTGRES_HOST", "localhost")
        self.port = port or int(os.getenv("POSTGRES_PORT", "5432"))
        self.database = database or os.getenv("POSTGRES_DB", "postgres")
        self.user = user or os.getenv("POSTGRES_USER", "postgres")
        self.password = password or os.getenv("POSTGRES_PASSWORD", "")

        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size

        self._pool: Optional[Pool] = None

    async def connect(self) -> None:
        """
        Establish connection pool to PostgreSQL server.

        Raises:
            Exception: If connection fails
        """
        if self._connected and self._pool:
            print(f"[{self.name}] Already connected")
            return

        try:
            print(
                f"[{self.name}] Connecting to PostgreSQL at {self.host}:{self.port}..."
            )

            self._pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
            )

            self._connected = True
            print(
                f"[{self.name}] ✓ Connected to PostgreSQL "
                f"(pool: {self.min_pool_size}-{self.max_pool_size} connections)"
            )

        except Exception as e:
            self._connected = False
            print(f"[{self.name}] ✗ Failed to connect to PostgreSQL: {e}")
            raise

    async def disconnect(self) -> None:
        """Close all connections in the pool."""
        if not self._connected or not self._pool:
            print(f"[{self.name}] Not connected")
            return

        try:
            await self._pool.close()
            self._pool = None
            self._connected = False
            print(f"[{self.name}] ✓ Disconnected from PostgreSQL")

        except Exception as e:
            print(f"[{self.name}] ✗ Error during disconnect: {e}")
            raise

    async def health_check(self) -> bool:
        """
        Check if PostgreSQL server is healthy and responding.

        Returns:
            bool: True if healthy, False otherwise
        """
        if not self._connected or not self._pool:
            return False

        try:
            async with self._pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                return result == 1

        except Exception as e:
            print(f"[{self.name}] Health check failed: {e}")
            return False

    @asynccontextmanager
    async def acquire(self):
        """
        Context manager to acquire a connection from the pool.

        Usage:
            async with server.acquire() as conn:
                result = await conn.fetch("SELECT * FROM users")
        """
        if not self._pool:
            raise RuntimeError(f"[{self.name}] Not connected to PostgreSQL")

        async with self._pool.acquire() as connection:
            yield connection

    async def execute(self, query: str, *args) -> str:
        """
        Execute a SQL query that doesn't return data (INSERT, UPDATE, DELETE).

        Args:
            query: SQL query string
            *args: Query parameters

        Returns:
            str: Status of the executed command
        """
        if not self._pool:
            raise RuntimeError(f"[{self.name}] Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args) -> List[Dict[str, Any]]:
        """
        Execute a SQL query and fetch all results.

        Args:
            query: SQL query string
            *args: Query parameters

        Returns:
            List of dictionaries containing query results
        """
        if not self._pool:
            raise RuntimeError(f"[{self.name}] Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
            return [dict(row) for row in rows]

    async def fetchrow(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """
        Execute a SQL query and fetch a single row.

        Args:
            query: SQL query string
            *args: Query parameters

        Returns:
            Dictionary containing query result or None
        """
        if not self._pool:
            raise RuntimeError(f"[{self.name}] Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
            return dict(row) if row else None

    async def fetchval(self, query: str, *args, column: int = 0) -> Any:
        """
        Execute a SQL query and fetch a single value.

        Args:
            query: SQL query string
            *args: Query parameters
            column: Column index to return (default: 0)

        Returns:
            Single value from the query result
        """
        if not self._pool:
            raise RuntimeError(f"[{self.name}] Not connected to PostgreSQL")

        async with self._pool.acquire() as conn:
            return await conn.fetchval(query, *args, column=column)

    async def create_table(self, table_schema: str) -> None:
        """
        Create a table using the provided schema.

        Args:
            table_schema: SQL CREATE TABLE statement
        """
        await self.execute(table_schema)
        print(f"[{self.name}] ✓ Table created successfully")

    async def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in the database.

        Args:
            table_name: Name of the table to check

        Returns:
            bool: True if table exists, False otherwise
        """
        query = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = $1
            );
        """
        return await self.fetchval(query, table_name)

    @property
    def pool(self) -> Optional[Pool]:
        """Get the connection pool instance."""
        return self._pool
