"""
In-memory MySQL server handler for testing.

This module provides an in-memory SQLite-based implementation that mimics
MySQL behavior for testing purposes without requiring a real MySQL server.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite
from sqlalchemy import create_engine
from sqlalchemy.dialects import sqlite
from sqlalchemy.sql import ddl

from source.server.db_models import SQL_DATABASE_MODELS
from source.server.services import SQLDatabase

logger = logging.getLogger(__name__)


# -------------------------------------------------------------- #
# In-Memory MySQL Server Handler (SQLite-based)
# -------------------------------------------------------------- #


class InMemoryMySQLServer(SQLDatabase):
    """Handler for in-memory SQLite database (mimics MySQL for testing)."""

    def __init__(self, name: str = "test_mysql"):
        """
        Initialize in-memory MySQL server handler.

        Args:
            name: Name of the server handler
        """
        # Use in-memory SQLite database
        conn_str = "sqlite+aiosqlite:///:memory:"
        super().__init__(name, conn_str)
        self.connection: aiosqlite.Connection | None = None
        self._engine = None

    # -------------------------------------------------------------- #
    # Connection Management
    # -------------------------------------------------------------- #

    async def connect(self) -> None:
        """Establish connection to in-memory SQLite database."""
        try:
            # Create in-memory database connection
            self.connection = await aiosqlite.connect(":memory:")
            self.connection.row_factory = aiosqlite.Row

            # Create SQLAlchemy engine for query compilation
            self._engine = create_engine("sqlite:///:memory:")

            self._connected = True
            logger.info(f"[{self.name}] Connected to in-memory SQLite database")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to connect: {e}")
            self._connected = False
            raise

    async def disconnect(self) -> None:
        """Close connection to in-memory database."""
        try:
            if self.connection:
                await self.connection.close()
                self.connection = None
            if self._engine:
                self._engine.dispose()
                self._engine = None
            self._connected = False
            logger.info(f"[{self.name}] Disconnected from in-memory database")
        except Exception as e:
            logger.error(f"[{self.name}] Error during disconnect: {e}")
            raise

    async def health_check(self) -> bool:
        """Check if database is healthy."""
        try:
            if not self.connection:
                return False
            # Simple query to check connection
            async with self.connection.execute("SELECT 1") as cursor:
                result = await cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"[{self.name}] Health check failed: {e}")
            return False

    # -------------------------------------------------------------- #
    # Database Operations
    # -------------------------------------------------------------- #

    async def create_tables(self) -> None:
        """Create database tables from models."""
        try:
            if not self.connection:
                raise RuntimeError("Not connected to database")

            logger.info(f"[{self.name}] Creating tables...")

            for model in SQL_DATABASE_MODELS:
                # Generate CREATE TABLE statement using SQLAlchemy
                create_stmt = ddl.CreateTable(model.__table__, if_not_exists=True)
                sql = str(create_stmt.compile(dialect=sqlite.dialect()))

                logger.debug(f"[{self.name}] Executing: {sql}")
                await self.connection.execute(sql)

            await self.connection.commit()
            logger.info(f"[{self.name}] Tables created successfully")

        except Exception as e:
            logger.error(f"[{self.name}] Failed to create tables: {e}")
            raise

    def compile_query_object(self, stmt) -> str:
        """
        Compile a SQLAlchemy statement object into a SQL query string.

        Args:
            stmt: SQLAlchemy statement object

        Returns:
            Compiled SQL query string
        """
        try:
            if not self._engine:
                raise RuntimeError("Engine not initialized")

            compiled = stmt.compile(
                dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
            )
            return str(compiled)
        except Exception as e:
            logger.error(f"[{self.name}] Failed to compile query: {e}")
            raise

    @asynccontextmanager
    async def _get_connection(self):
        """Get database connection context manager."""
        if not self.connection:
            raise RuntimeError("Not connected to database")
        yield self.connection

    async def execute(self, stmt) -> list[dict[str, Any]]:
        """
        Execute a SQLAlchemy statement and return results.

        Args:
            stmt: SQLAlchemy statement object (select, insert, update, delete)

        Returns:
            List of result rows as dictionaries (empty list for non-SELECT queries)
        """
        try:
            sql = self.compile_query_object(stmt)
            logger.debug(f"[{self.name}] Executing: {sql}")

            async with self._get_connection() as conn, conn.execute(sql) as cursor:
                rows = await cursor.fetchall()
                await conn.commit()

                # Convert rows to dictionaries
                if rows:
                    return [dict(row) for row in rows]
                return []

        except Exception as e:
            logger.error(f"[{self.name}] Query execution failed: {e}")
            raise

    async def execute_many(self, stmt, values: list[dict]) -> None:
        """
        Execute a SQLAlchemy statement with multiple parameter sets.

        Args:
            stmt: SQLAlchemy statement object
            values: List of parameter dictionaries
        """
        try:
            # Get base SQL
            sql = self.compile_query_object(stmt)

            async with self._get_connection() as conn:
                await conn.executemany(sql, values)
                await conn.commit()

        except Exception as e:
            logger.error(f"[{self.name}] Batch execution failed: {e}")
            raise
