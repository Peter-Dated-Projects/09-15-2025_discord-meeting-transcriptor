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
        """Create all database tables from the defined models and update existing tables."""
        try:

            # Create engine for SQLAlchemy table creation
            connection_string = f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            engine = create_engine(connection_string)

            # Create all tables from the models
            # Note: This uses synchronous engine, but it's only during initialization
            logger.info(f"[{self.name}] Creating/updating database tables...")

            for model in SQL_DATABASE_MODELS:
                table_name = model.__tablename__

                # Check if table exists
                async with self._get_connection() as connection:
                    result = await connection.fetchval(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema = 'public' AND table_name = $1",
                        table_name,
                    )
                    table_exists = result > 0

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
        try:
            # Get current columns from database
            async with self._get_connection() as connection:
                db_columns_rows = await connection.fetch(
                    "SELECT column_name, data_type, is_nullable, udt_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = $1",
                    table_name,
                )
                db_columns = {row["column_name"]: row for row in db_columns_rows}

                # Get model columns
                model_columns = {col.name: col for col in model.__table__.columns}

                # Find columns to add
                columns_to_add = set(model_columns.keys()) - set(db_columns.keys())
                # Find columns to remove
                columns_to_remove = set(db_columns.keys()) - set(model_columns.keys())
                # Find columns to potentially modify
                columns_to_check = set(model_columns.keys()) & set(db_columns.keys())

                # Add missing columns
                for col_name in columns_to_add:
                    col = model_columns[col_name]
                    col_type = self._get_postgresql_column_type(col)
                    nullable = "" if col.nullable else "NOT NULL"
                    default = ""
                    if col.default is not None and hasattr(col.default, "arg"):
                        default_val = col.default.arg
                        if isinstance(default_val, str):
                            default = f"DEFAULT '{default_val}'"
                        else:
                            default = f"DEFAULT {default_val}"

                    alter_query = f'ALTER TABLE "{table_name}" ADD COLUMN "{col_name}" {col_type} {nullable} {default}'
                    await connection.execute(alter_query)
                    logger.info(f"[{self.name}] Added column `{col_name}` to table `{table_name}`")

                # Modify existing columns if needed
                for col_name in columns_to_check:
                    col = model_columns[col_name]
                    db_col = db_columns[col_name]

                    # Check if column needs modification
                    model_col_type = self._get_postgresql_column_type(col)
                    db_col_type = db_col["data_type"].upper()

                    # Compare types (normalize for comparison)
                    if model_col_type.upper() != db_col_type:
                        nullable = "" if col.nullable else "NOT NULL"
                        default = ""
                        if col.default is not None and hasattr(col.default, "arg"):
                            default_val = col.default.arg
                            if isinstance(default_val, str):
                                default = f"DEFAULT '{default_val}'"
                            else:
                                default = f"DEFAULT {default_val}"

                        alter_query = f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" TYPE {model_col_type} {nullable} {default}'
                        await connection.execute(alter_query)
                        logger.info(
                            f"[{self.name}] Modified column `{col_name}` in table `{table_name}` from {db_col_type} to {model_col_type}"
                        )

                # Remove extra columns
                for col_name in columns_to_remove:
                    alter_query = f'ALTER TABLE "{table_name}" DROP COLUMN "{col_name}"'
                    await connection.execute(alter_query)
                    logger.info(
                        f"[{self.name}] Removed column `{col_name}` from table `{table_name}`"
                    )

        except Exception as e:
            logger.error(f"[{self.name}] Error updating table schema for {table_name}: {e}")
            raise

    def _get_postgresql_column_type(self, column) -> str:
        """
        Convert SQLAlchemy column type to PostgreSQL column type string.

        Args:
            column: SQLAlchemy Column object

        Returns:
            PostgreSQL column type string
        """
        col_type = column.type
        type_name = col_type.__class__.__name__

        if type_name == "String":
            length = col_type.length if hasattr(col_type, "length") and col_type.length else 255
            return f"VARCHAR({length})"
        elif type_name == "Integer":
            return "INTEGER"
        elif type_name == "DateTime":
            return "TIMESTAMP"
        elif type_name == "JSON":
            return "JSONB"
        elif type_name == "Enum":
            # For PostgreSQL, we need to use the enum type name
            # This assumes the enum type already exists or will be created
            if hasattr(col_type, "name"):
                return col_type.name
            else:
                # Fallback to VARCHAR if enum name not available
                return "VARCHAR(255)"
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
