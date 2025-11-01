"""
PostgreSQL server handler for database operations.

This module provides an object-oriented handler for managing connections
and operations with PostgreSQL database using SQLAlchemy Core for query building.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from asyncpg import Pool
from sqlalchemy import (
    MetaData,
    Table,
    delete,
    insert,
    update,
)
from sqlalchemy.dialects import postgresql

from ..services import SQLDatabase

logger = logging.getLogger(__name__)


# -------------------------------------------------------------- #
# PostgreSQL Server Handler
# -------------------------------------------------------------- #


class PostgreSQLServer(SQLDatabase):
    """Handler for PostgreSQL database server operations."""

    def __init__(
        self,
        name: str = "postgresql",
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        connection_string: str | None = None,
    ):
        """
        Initialize PostgreSQL server handler.

        Args:
            name: Name of the server handler
            host: PostgreSQL server host
            port: PostgreSQL server port (default: 5432)
            user: Database user
            password: Database password
            database: Database name
            connection_string: Full connection string (overrides individual params)
        """
        # Store parameters first
        self.host = host or os.getenv("POSTGRES_HOST", "localhost")
        self.port = port or int(os.getenv("POSTGRES_PORT", "5432"))
        self.user = user or os.getenv("POSTGRES_USER", "postgres")
        self.password = password or os.getenv("POSTGRES_PASSWORD", "")
        self.database = database or os.getenv("POSTGRES_DB", "postgres")

        # Build connection string
        if connection_string:
            conn_str = connection_string
        else:
            conn_str = (
                f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            )

        super().__init__(name, conn_str)

        self.pool: Pool | None = None

    # -------------------------------------------------------------- #
    # Connection Management
    # -------------------------------------------------------------- #

    async def connect(self) -> None:
        """Establish connection pool to PostgreSQL server."""
        try:
            self.pool = await asyncpg.create_pool(
                self.connection_string,
                min_size=1,
                max_size=10,
                command_timeout=60,
            )
            self._connected = True
            logger.info(f"[{self.name}] Connected to PostgreSQL")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to connect: {e}")
            self._connected = False
            raise

    async def disconnect(self) -> None:
        """Close connection pool to PostgreSQL server."""
        if self.pool:
            try:
                await self.pool.close()
                self._connected = False
                logger.info(f"[{self.name}] Disconnected from PostgreSQL")
            except Exception as e:
                logger.error(f"[{self.name}] Failed to disconnect: {e}")
                raise

    async def health_check(self) -> bool:
        """Check if the PostgreSQL server is healthy and responding."""
        if not self.pool:
            return False

        try:
            async with self.pool.acquire() as connection:
                result = await connection.fetchval("SELECT 1")
                is_healthy = result == 1
                if is_healthy:
                    logger.debug(f"[{self.name}] Health check passed")
                else:
                    logger.warning(f"[{self.name}] Health check failed")
                return is_healthy
        except Exception as e:
            logger.error(f"[{self.name}] Health check error: {e}")
            return False

    @asynccontextmanager
    async def _get_connection(self):
        """Context manager for getting a database connection from the pool."""
        if not self.pool:
            raise RuntimeError(f"[{self.name}] Connection pool not initialized")

        connection = await self.pool.acquire()
        try:
            yield connection
        finally:
            await self.pool.release(connection)

    # -------------------------------------------------------------- #
    # CRUD Operations
    # -------------------------------------------------------------- #

    async def query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Execute a SQL SELECT query.

        Args:
            query: SQL query string with $1, $2, etc. for parameters
            params: Optional parameters dictionary

        Returns:
            List of result rows as dictionaries
        """
        try:
            async with self._get_connection() as connection:
                param_values = list(params.values()) if params else []
                rows = await connection.fetch(query, *param_values)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"[{self.name}] Query error: {e}")
            raise

    async def insert(self, table: str, data: dict[str, Any]) -> None:
        """
        Insert data into a table using SQLAlchemy query builder.

        Args:
            table: Table name
            data: Data to insert as a dictionary

        Raises:
            ValueError: If data is empty
        """
        if not data:
            raise ValueError("Insert data cannot be empty")

        try:
            # Build INSERT statement with SQLAlchemy
            metadata = MetaData()
            table_obj = Table(table, metadata, autoload_with=None)
            stmt = insert(table_obj).values(**data)

            # Compile to PostgreSQL dialect with named parameters
            compiled = stmt.compile(dialect=postgresql.dialect())
            query_str = str(compiled)
            params = compiled.params
            param_values = list(params.values()) if params else list(data.values())

            async with self._get_connection() as connection:
                await connection.execute(query_str, *param_values)
                logger.debug(f"[{self.name}] Inserted into {table}")
        except Exception as e:
            logger.error(f"[{self.name}] Insert error: {e}")
            raise

    async def update(
        self,
        table: str,
        data: dict[str, Any],
        conditions: dict[str, Any],
    ) -> None:
        """
        Update data in a table using SQLAlchemy query builder.

        Args:
            table: Table name
            data: Data to update as a dictionary
            conditions: Conditions for the update as a dictionary

        Raises:
            ValueError: If data or conditions are empty
        """
        if not data:
            raise ValueError("Update data cannot be empty")
        if not conditions:
            raise ValueError("Update conditions cannot be empty")

        try:
            # Build UPDATE statement with SQLAlchemy
            metadata = MetaData()
            table_obj = Table(table, metadata, autoload_with=None)

            # Build WHERE clause
            where_clause = None
            for key, value in conditions.items():
                condition = table_obj.c[key] == value
                where_clause = condition if where_clause is None else where_clause & condition

            stmt = update(table_obj).where(where_clause).values(**data)

            # Compile to PostgreSQL dialect
            compiled = stmt.compile(dialect=postgresql.dialect())
            query_str = str(compiled)
            params = compiled.params
            param_values = list(params.values())

            async with self._get_connection() as connection:
                await connection.execute(query_str, *param_values)
                logger.debug(f"[{self.name}] Updated {table}")
        except Exception as e:
            logger.error(f"[{self.name}] Update error: {e}")
            raise

    async def delete(self, table: str, conditions: dict[str, Any]) -> None:
        """
        Delete data from a table using SQLAlchemy query builder.

        Args:
            table: Table name
            conditions: Conditions for the deletion as a dictionary

        Raises:
            ValueError: If conditions are empty
        """
        if not conditions:
            raise ValueError("Delete conditions cannot be empty")

        try:
            # Build DELETE statement with SQLAlchemy
            metadata = MetaData()
            table_obj = Table(table, metadata, autoload_with=None)

            # Build WHERE clause
            where_clause = None
            for key, value in conditions.items():
                condition = table_obj.c[key] == value
                where_clause = condition if where_clause is None else where_clause & condition

            stmt = delete(table_obj).where(where_clause)

            # Compile to PostgreSQL dialect
            compiled = stmt.compile(dialect=postgresql.dialect())
            query_str = str(compiled)
            params = compiled.params
            param_values = list(params.values())

            async with self._get_connection() as connection:
                await connection.execute(query_str, *param_values)
                logger.debug(f"[{self.name}] Deleted from {table}")
        except Exception as e:
            logger.error(f"[{self.name}] Delete error: {e}")
            raise
