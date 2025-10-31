"""
MySQL server handler for database operations.

This module provides an object-oriented handler for managing connections
and operations with MySQL database.
"""

import os
import logging
from typing import Optional, Any, Dict, List
from contextlib import asynccontextmanager
import aiomysql
from aiomysql import Pool, Connection

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
        host: Optional[str] = None,
        port: Optional[int] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
        connection_string: Optional[str] = None,
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
        if connection_string:
            super().__init__(name, connection_string)
        else:
            # Build connection string info from individual parameters
            host = host or os.getenv("MYSQL_HOST", "localhost")
            port = port or int(os.getenv("MYSQL_PORT", "3306"))
            user = user or os.getenv("MYSQL_USER", "root")
            password = password or os.getenv("MYSQL_PASSWORD", "")
            database = database or os.getenv("MYSQL_DB", "mysql")

            connection_string = f"mysql://{user}:{password}@{host}:{port}/{database}"
            super().__init__(name, connection_string)

        self.pool: Optional[Pool] = None
        self.host = host or os.getenv("MYSQL_HOST", "localhost")
        self.port = port or int(os.getenv("MYSQL_PORT", "3306"))
        self.user = user or os.getenv("MYSQL_USER", "root")
        self.password = password or os.getenv("MYSQL_PASSWORD", "")
        self.database = database or os.getenv("MYSQL_DB", "mysql")

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
            async with self.pool.acquire() as connection:
                async with connection.cursor() as cursor:
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

    async def query(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL SELECT query.

        Args:
            query: SQL query string with %(key)s for named parameters
            params: Optional parameters dictionary

        Returns:
            List of result rows as dictionaries
        """
        try:
            async with self._get_connection() as connection:
                async with connection.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, params)
                    rows = await cursor.fetchall()
                    return rows if rows else []
        except Exception as e:
            logger.error(f"[{self.name}] Query error: {e}")
            raise

    async def insert(self, table: str, data: Dict[str, Any]) -> None:
        """
        Insert data into a table.

        Args:
            table: Table name
            data: Data to insert as a dictionary

        Raises:
            ValueError: If data is empty
        """
        if not data:
            raise ValueError("Insert data cannot be empty")

        try:
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            values = list(data.values())

            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, values)
                    await connection.commit()
                    logger.debug(f"[{self.name}] Inserted into {table}")
        except Exception as e:
            logger.error(f"[{self.name}] Insert error: {e}")
            raise

    async def update(
        self,
        table: str,
        data: Dict[str, Any],
        conditions: Dict[str, Any],
    ) -> None:
        """
        Update data in a table.

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
            set_clause = ", ".join(f"{k} = %s" for k in data.keys())
            where_clause = " AND ".join(f"{k} = %s" for k in conditions.keys())
            query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
            values = list(data.values()) + list(conditions.values())

            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, values)
                    await connection.commit()
                    logger.debug(f"[{self.name}] Updated {table}")
        except Exception as e:
            logger.error(f"[{self.name}] Update error: {e}")
            raise

    async def delete(self, table: str, conditions: Dict[str, Any]) -> None:
        """
        Delete data from a table.

        Args:
            table: Table name
            conditions: Conditions for the deletion as a dictionary

        Raises:
            ValueError: If conditions are empty
        """
        if not conditions:
            raise ValueError("Delete conditions cannot be empty")

        try:
            where_clause = " AND ".join(f"{k} = %s" for k in conditions.keys())
            query = f"DELETE FROM {table} WHERE {where_clause}"
            values = list(conditions.values())

            async with self._get_connection() as connection:
                async with connection.cursor() as cursor:
                    await cursor.execute(query, values)
                    await connection.commit()
                    logger.debug(f"[{self.name}] Deleted from {table}")
        except Exception as e:
            logger.error(f"[{self.name}] Delete error: {e}")
            raise
