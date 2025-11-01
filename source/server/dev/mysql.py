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
    delete,
    insert,
    update,
)
from sqlalchemy.dialects import mysql

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
    # CRUD Operations
    # -------------------------------------------------------------- #

    async def query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """
        Execute a SQL SELECT query.

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
                rows = await cursor.fetchall()
                return rows if rows else []
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
            # Compile to MySQL dialect
            compiled = stmt.compile(dialect=mysql.dialect())
            query_str = str(compiled)
            params = compiled.params
            param_values = list(params.values()) if params else list(data.values())

            async with (
                self._get_connection() as connection,
                connection.cursor() as cursor,
            ):
                await cursor.execute(query_str, param_values)
                await connection.commit()
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

            # Compile to MySQL dialect
            compiled = stmt.compile(dialect=mysql.dialect())
            query_str = str(compiled)
            params = compiled.params
            param_values = list(params.values())

            async with (
                self._get_connection() as connection,
                connection.cursor() as cursor,
            ):
                await cursor.execute(query_str, param_values)
                await connection.commit()
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

            # Compile to MySQL dialect
            compiled = stmt.compile(dialect=mysql.dialect())
            query_str = str(compiled)
            params = compiled.params
            param_values = list(params.values())

            async with (
                self._get_connection() as connection,
                connection.cursor() as cursor,
            ):
                await cursor.execute(query_str, param_values)
                await connection.commit()
                logger.debug(f"[{self.name}] Deleted from {table}")
        except Exception as e:
            logger.error(f"[{self.name}] Delete error: {e}")
            raise
