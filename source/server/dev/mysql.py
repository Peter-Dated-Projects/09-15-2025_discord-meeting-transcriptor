"""
MySQL server handler for database operations.

This module provides an object-oriented handler for managing connections
and operations with MySQL database using SQLAlchemy Core for query building.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import aiomysql
from aiomysql import Pool
from sqlalchemy import (
    MetaData,
    Table,
    create_engine,
)
from sqlalchemy.dialects import mysql

from source.server.db_models import SQL_DATABASE_MODELS

from ..services import SQLDatabase

logger = logging.getLogger(__name__)


# -------------------------------------------------------------- #
# MySQL Server Handler
# -------------------------------------------------------------- #


class MySQLServer(SQLDatabase):
    """Handler for MySQL database server operations."""

    def __init__(
        self,
        name: str = "mysql",
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        connection_string: str | None = None,
    ):
        """
        Initialize MySQL server handler.

        Args:
            name: Name of the server handler
            host: MySQL server host
            port: MySQL server port (default: 3306)
            user: Database user
            password: Database password
            database: Database name
            connection_string: Full connection string (for compatibility)
        """
        # Store parameters first
        self.host = host or os.getenv("MYSQL_HOST", "localhost")
        self.port = port or int(os.getenv("MYSQL_PORT", "3306"))
        self.user = user or os.getenv("MYSQL_USER", "root")
        self.password = password or os.getenv("MYSQL_PASSWORD", "")
        self.database = database or os.getenv("MYSQL_DB", "mysql")

        # Build connection string
        if connection_string:
            conn_str = connection_string
        else:
            conn_str = (
                f"mysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            )

        super().__init__(name, conn_str)

        self.pool: Pool | None = None

    # -------------------------------------------------------------- #
    # Connection Management
    # -------------------------------------------------------------- #

    async def connect(self) -> None:
        """Establish connection pool to MySQL server."""
        try:
            self.pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.database,
                minsize=1,
                maxsize=10,
            )
            self._connected = True
            logger.info(f"[{self.name}] Connected to MySQL")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to connect: {e}")
            self._connected = False
            raise

    async def disconnect(self) -> None:
        """Close connection pool to MySQL server."""
        if self.pool:
            try:
                self.pool.close()
                await self.pool.wait_closed()
                self._connected = False
                logger.info(f"[{self.name}] Disconnected from MySQL")
            except Exception as e:
                logger.error(f"[{self.name}] Failed to disconnect: {e}")
                raise

    async def health_check(self) -> bool:
        """Check if the MySQL server is healthy and responding."""
        if not self.pool:
            return False

        try:
            async with self.pool.acquire() as connection, connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                result = await cursor.fetchone()
                is_healthy = result is not None and result[0] == 1
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
            connection_string = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
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
            self.pool.release(connection)

    # -------------------------------------------------------------- #
    # Utils
    # -------------------------------------------------------------- #

    def compile_query_object(self, stmt) -> str:
        """
        Compile a SQLAlchemy statement to a MySQL query string and parameters.

        Args:
            stmt: SQLAlchemy statement object
        Returns:
            Compiled query string
        """
        compiled = stmt.compile(dialect=mysql.dialect())
        query_str = str(compiled)
        return query_str

    async def execute(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Execute a SQL query and return results.

        Args:
            query: SQL query string with %(key)s for named parameters
            params: Optional parameters dictionary

        Returns:
            List of result rows as dictionaries
        """
        try:
            async with (
                self._get_connection() as connection,
                connection.cursor(aiomysql.DictCursor) as cursor,
            ):
                await cursor.execute(query, params)
                
                # Check if this is a SELECT query (returns results)
                if query.strip().upper().startswith('SELECT'):
                    rows = await cursor.fetchall()
                    return rows if rows else []
                else:
                    # For INSERT, UPDATE, DELETE - commit and return empty list
                    await connection.commit()
                    return []
        except Exception as e:
            logger.error(f"[{self.name}] Execute error: {e}")
            raise
