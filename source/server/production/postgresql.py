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
    create_engine,
)
from sqlalchemy.dialects import postgresql

from source.server.db_models import SQL_DATABASE_MODELS

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

    async def create_tables(self) -> None:
        """Create all database tables from the defined models."""
        try:

            # Create engine for SQLAlchemy table creation
            connection_string = f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            engine = create_engine(connection_string)

            # Create all tables from the models
            # Note: This uses synchronous engine, but it's only during initialization
            logger.info(f"[{self.name}] Creating database tables...")

            for model in SQL_DATABASE_MODELS:
                model.metadata.create_all(engine, [model.__table__], checkfirst=True)
                logger.info(f"[{self.name}] Created/verified table: {model.__tablename__}")

            logger.info(f"[{self.name}] All tables created/verified successfully")
            engine.dispose()
        except Exception as e:
            logger.error(f"[{self.name}] Error creating tables: {e}")
            # Don't raise - continue with connection even if table creation fails
            # in case tables already exist

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
    # Utils
    # -------------------------------------------------------------- #

    def compile_query_object(self, stmt) -> str:
        """
        Compile a SQLAlchemy statement object into a SQL query string.

        Args:
            stmt: SQLAlchemy statement object

        Returns:
            Compiled SQL query string
        """
        compiled = stmt.compile(dialect=postgresql.dialect())
        return str(compiled)

    async def execute(self, stmt) -> list[dict[str, Any]]:
        """
        Execute a SQLAlchemy statement and return results.

        Args:
            stmt: SQLAlchemy statement object (select, insert, update, delete)

        Returns:
            List of result rows as dictionaries (empty list for non-SELECT queries)
        """
        try:
            # Compile the statement to SQL string with literal binds
            compiled = stmt.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
            query = str(compiled)

            async with self._get_connection() as connection:
                # Check if this is a SELECT query (returns results)
                if query.strip().upper().startswith("SELECT"):
                    rows = await connection.fetch(query)
                    return [dict(row) for row in rows]
                else:
                    # For INSERT, UPDATE, DELETE - execute and return empty list
                    await connection.execute(query)
                    return []
        except Exception as e:
            logger.error(f"[{self.name}] Execute error: {e}")
            raise
