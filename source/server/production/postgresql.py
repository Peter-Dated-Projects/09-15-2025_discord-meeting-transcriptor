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
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import DDL
from sqlalchemy.sql import ddl

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

                # Check if table exists using SQLAlchemy Inspector
                temp_connection_string = f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
                temp_engine = create_engine(temp_connection_string)
                inspector = inspect(temp_engine)

                table_exists = table_name in inspector.get_table_names()
                temp_engine.dispose()

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
            # Use SQLAlchemy Inspector to get current columns from database
            temp_connection_string = f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
            temp_engine = create_engine(temp_connection_string)
            inspector = inspect(temp_engine)

            # Get database columns info
            db_columns_list = inspector.get_columns(table_name)
            db_columns = {col["name"]: col for col in db_columns_list}
            temp_engine.dispose()

            # Get model columns
            model_columns = {col.name: col for col in model.__table__.columns}

            # Find columns to add
            columns_to_add = set(model_columns.keys()) - set(db_columns.keys())
            # Find columns to remove
            columns_to_remove = set(db_columns.keys()) - set(model_columns.keys())
            # Find columns to potentially modify
            columns_to_check = set(model_columns.keys()) & set(db_columns.keys())

            # Add missing columns using SQLAlchemy DDL
            for col_name in columns_to_add:
                col = model_columns[col_name]
                # Get the actual Column object from the model
                column_to_add = model.__table__.columns[col_name]

                # Compile the column type for PostgreSQL
                col_type = column_to_add.type.compile(dialect=postgresql.dialect())
                nullable = "NULL" if column_to_add.nullable else "NOT NULL"
                
                # Build DDL statement
                add_column_ddl = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type} {nullable}"
                stmt = DDL(add_column_ddl)
                
                await self.execute(stmt)
                logger.info(f"[{self.name}] Added column `{col_name}` to table `{table_name}`")

            # Modify existing columns if needed
            # PostgreSQL uses ALTER COLUMN TYPE syntax
            for col_name in columns_to_check:
                col = model_columns[col_name]
                db_col = db_columns[col_name]

                # Check if column needs modification
                model_col_type = self._get_postgresql_column_type(col)
                # Inspector returns type object, need to convert to string for comparison
                db_col_type = str(db_col["type"]).upper()

                # Compare types (normalize for comparison)
                if (
                    model_col_type.upper() not in db_col_type
                    and db_col_type not in model_col_type.upper()
                ):
                    # Use DDL for ALTER COLUMN TYPE (PostgreSQL-specific)
                    # Note: PostgreSQL requires separate ALTER statements for type, nullable, and default
                    stmt = ddl.DDL(
                        f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" TYPE {model_col_type}'
                    )
                    await self.execute(stmt)

                    # Set nullable constraint if needed
                    if not col.nullable:
                        stmt = ddl.DDL(
                            f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" SET NOT NULL'
                        )
                        await self.execute(stmt)
                    else:
                        stmt = ddl.DDL(
                            f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" DROP NOT NULL'
                        )
                        await self.execute(stmt)

                    # Set default value if specified
                    if col.default is not None and hasattr(col.default, "arg"):
                        default_val = col.default.arg
                        if isinstance(default_val, str):
                            stmt = ddl.DDL(
                                f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" SET DEFAULT \'{default_val}\''
                            )
                        else:
                            stmt = ddl.DDL(
                                f'ALTER TABLE "{table_name}" ALTER COLUMN "{col_name}" SET DEFAULT {default_val}'
                            )
                        await self.execute(stmt)

                    logger.info(
                        f"[{self.name}] Modified column `{col_name}` in table `{table_name}` from {db_col_type} to {model_col_type}"
                    )

            # Remove extra columns using SQLAlchemy DDL
            for col_name in columns_to_remove:
                # Build DDL statement to drop column
                drop_column_ddl = f"ALTER TABLE {table_name} DROP COLUMN {col_name}"
                stmt = DDL(drop_column_ddl)
                
                await self.execute(stmt)
                logger.info(f"[{self.name}] Removed column `{col_name}` from table `{table_name}`")

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
            # Extract table name from the statement for better error context
            table_name = "unknown"
            operation = "unknown"
            try:
                if hasattr(stmt, "table"):
                    table_name = str(stmt.table.name)
                elif hasattr(stmt, "froms") and stmt.froms:
                    table_name = str(stmt.froms[0].name)

                # Determine operation type
                stmt_str = str(type(stmt).__name__).lower()
                if "insert" in stmt_str:
                    operation = "INSERT"
                elif "update" in stmt_str:
                    operation = "UPDATE"
                elif "delete" in stmt_str:
                    operation = "DELETE"
                elif "select" in stmt_str:
                    operation = "SELECT"
            except Exception:
                pass  # If we can't extract metadata, just continue with 'unknown'

            logger.error(
                f"CRITICAL SQL ERROR [{self.name}] - Operation: {operation}, Table: {table_name}, "
                f"Error Type: {type(e).__name__}, Details: {str(e)}"
            )
            if "query" in locals():
                logger.error(f"[{self.name}] Query: {query}")

            # Additional context for foreign key violations
            error_str = str(e).lower()
            if "foreign key" in error_str or "constraint" in error_str:
                logger.error(
                    f"[{self.name}] FOREIGN KEY CONSTRAINT VIOLATION detected! "
                    f"This typically means a referenced record doesn't exist in the parent table. "
                    f"Check that all foreign key references (e.g., meeting_id) exist before inserting."
                )

            raise
