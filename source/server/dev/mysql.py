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
        """Create all database tables from the defined models and update existing tables."""
        try:

            # Create engine for SQLAlchemy table creation
            connection_string = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            engine = create_engine(connection_string)

            # Create all tables from the models
            # Note: This uses synchronous engine, but it's only during initialization
            logger.info(f"[{self.name}] Creating/updating database tables...")

            for model in SQL_DATABASE_MODELS:
                table_name = model.__tablename__
                
                # Check if table exists
                async with (
                    self._get_connection() as connection,
                    connection.cursor(aiomysql.DictCursor) as cursor,
                ):
                    await cursor.execute(
                        "SELECT COUNT(*) as count FROM information_schema.tables "
                        "WHERE table_schema = %s AND table_name = %s",
                        (self.database, table_name)
                    )
                    result = await cursor.fetchone()
                    table_exists = result['count'] > 0

                if not table_exists:
                    # Create new table
                    model.metadata.create_all(engine, [model.__table__], checkfirst=True)
                    logger.info(f"[{self.name}] Created table: {table_name}")
                else:
                    # Update existing table
                    await self._update_table_schema(model, table_name)
                    logger.info(f"[{self.name}] Updated/verified table: {table_name}")

            logger.info(f"[{self.name}] All tables created/updated successfully")
            engine.dispose()
        except Exception as e:
            logger.error(f"[{self.name}] Error creating/updating tables: {e}")
            # Don't raise - continue with connection even if table creation fails
            # in case tables already exist

    async def _update_table_schema(self, model, table_name: str) -> None:
        """
        Update an existing table schema to match the model definition.
        
        Args:
            model: SQLAlchemy model class
            table_name: Name of the table to update
        """
        async with (
            self._get_connection() as connection,
            connection.cursor(aiomysql.DictCursor) as cursor,
        ):
            try:
                # Get current columns from database
                await cursor.execute(
                    "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_TYPE "
                    "FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s",
                    (self.database, table_name)
                )
                db_columns = {row['COLUMN_NAME']: row for row in await cursor.fetchall()}
                
                # Get model columns
                model_columns = {col.name: col for col in model.__table__.columns}
                
                # Find columns to add
                columns_to_add = set(model_columns.keys()) - set(db_columns.keys())
                # Find columns to remove
                columns_to_remove = set(db_columns.keys()) - set(model_columns.keys())
                
                # Add missing columns
                for col_name in columns_to_add:
                    col = model_columns[col_name]
                    col_type = self._get_mysql_column_type(col)
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    if col.default is not None:
                        if hasattr(col.default, 'arg'):
                            default_val = col.default.arg
                            if isinstance(default_val, str):
                                default = f"DEFAULT '{default_val}'"
                            else:
                                default = f"DEFAULT {default_val}"
                    
                    alter_query = f"ALTER TABLE `{table_name}` ADD COLUMN `{col_name}` {col_type} {nullable} {default}"
                    await cursor.execute(alter_query)
                    await connection.commit()
                    logger.info(f"[{self.name}] Added column `{col_name}` to table `{table_name}`")
                
                # Remove extra columns
                for col_name in columns_to_remove:
                    alter_query = f"ALTER TABLE `{table_name}` DROP COLUMN `{col_name}`"
                    await cursor.execute(alter_query)
                    await connection.commit()
                    logger.info(f"[{self.name}] Removed column `{col_name}` from table `{table_name}`")
                    
            except Exception as e:
                logger.error(f"[{self.name}] Error updating table schema for {table_name}: {e}")
                raise

    def _get_mysql_column_type(self, column) -> str:
        """
        Convert SQLAlchemy column type to MySQL column type string.
        
        Args:
            column: SQLAlchemy Column object
            
        Returns:
            MySQL column type string
        """
        col_type = column.type
        type_name = col_type.__class__.__name__
        
        if type_name == "String":
            length = col_type.length if hasattr(col_type, 'length') and col_type.length else 255
            return f"VARCHAR({length})"
        elif type_name == "Integer":
            return "INTEGER"
        elif type_name == "DateTime":
            return "DATETIME"
        elif type_name == "JSON":
            return "JSON"
        elif type_name == "Enum":
            # Get enum values
            enum_values = ",".join([f"'{e.value}'" for e in col_type.enum_class])
            return f"ENUM({enum_values})"
        else:
            return str(col_type)

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

    async def execute(self, stmt) -> list[dict[str, Any]]:
        """
        Execute a SQLAlchemy statement and return results.

        Args:
            stmt: SQLAlchemy statement object (select, insert, update, delete)

        Returns:
            List of result rows as dictionaries (empty list for non-SELECT queries)
        """
        try:
            # Compile the statement to SQL string
            compiled = stmt.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True})
            query = str(compiled)

            async with (
                self._get_connection() as connection,
                connection.cursor(aiomysql.DictCursor) as cursor,
            ):
                await cursor.execute(query)

                # Check if this is a SELECT query (returns results)
                if query.strip().upper().startswith("SELECT"):
                    rows = await cursor.fetchall()
                    return rows if rows else []
                else:
                    # For INSERT, UPDATE, DELETE - commit and return empty list
                    await connection.commit()
                    return []
        except Exception as e:
            logger.error(f"[{self.name}] Execute error: {e}")
            raise
