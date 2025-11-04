"""
MySQL server handler for database operations.

This module provides an object-oriented handler for managing connections
and operations with MySQL database using SQLAlchemy Core for query building.
"""

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

import aiomysql
from aiomysql import Pool
from sqlalchemy import Column, String, create_engine, inspect
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import AddColumn, DropColumn
from sqlalchemy.sql import ddl

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

                # Check if table exists using SQLAlchemy Inspector

                # Create a temporary engine to use inspector
                temp_connection_string = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
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
            temp_connection_string = f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
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

                stmt = AddColumn(table_name, column_to_add)
                await self.execute(stmt)
                logger.info(f"[{self.name}] Added column `{col_name}` to table `{table_name}`")

            # Modify existing columns if needed
            # Note: SQLAlchemy doesn't have a built-in AlterColumn for modifications,
            # so we use DDL() for MySQL-specific MODIFY COLUMN syntax
            for col_name in columns_to_check:
                col = model_columns[col_name]
                db_col = db_columns[col_name]

                # Check if column needs modification
                model_col_type = self._get_mysql_column_type(col)
                # Inspector returns type object, need to convert to string for comparison
                db_col_type = str(db_col["type"]).upper()

                # Compare types (normalize for comparison)
                if (
                    model_col_type.upper() not in db_col_type
                    and db_col_type not in model_col_type.upper()
                ):
                    nullable = "NULL" if col.nullable else "NOT NULL"
                    default = ""
                    if col.default is not None and hasattr(col.default, "arg"):
                        default_val = col.default.arg
                        if isinstance(default_val, str):
                            default = f"DEFAULT '{default_val}'"
                        else:
                            default = f"DEFAULT {default_val}"

                    # Use DDL for MODIFY COLUMN (MySQL-specific)
                    stmt = ddl.DDL(
                        f"ALTER TABLE `{table_name}` MODIFY COLUMN `{col_name}` {model_col_type} {nullable} {default}"
                    )
                    await self.execute(stmt)
                    logger.info(
                        f"[{self.name}] Modified column `{col_name}` in table `{table_name}` from {db_col_type} to {model_col_type}"
                    )

            # Remove extra columns using SQLAlchemy DDL
            for col_name in columns_to_remove:
                # Create a temporary Column object for DropColumn
                temp_col = Column(col_name, String)

                stmt = DropColumn(table_name, temp_col)
                await self.execute(stmt)
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
            length = col_type.length if hasattr(col_type, "length") and col_type.length else 255
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
            # Compile the statement for MySQL dialect
            from sqlalchemy.dialects.mysql import pymysql

            compiled = stmt.compile(dialect=pymysql.dialect())

            # Get the query string and parameters
            query = str(compiled)
            params = compiled.params

            # Debug: log the original query to see the format
            logger.debug(f"[{self.name}] Original compiled query: {query}")
            logger.debug(f"[{self.name}] Original params: {params}")

            # Convert dict/list parameters to JSON strings for MySQL
            # But keep list parameters that are for IN clauses as lists
            processed_params = {}
            for key, value in params.items():
                if isinstance(value, dict):
                    # Dict should be JSON
                    processed_params[key] = json.dumps(value)
                elif isinstance(value, list):
                    # Lists in IN clauses should stay as lists, not be JSON encoded
                    # We'll handle them specially below
                    processed_params[key] = value
                else:
                    processed_params[key] = value

            # Extract parameter names in order from the query

            # Check for POSTCOMPILE parameters (used for IN clause expansion)
            postcompile_pattern = re.compile(r"__\[POSTCOMPILE_(\w+)\]")
            postcompile_matches = postcompile_pattern.findall(query)

            if postcompile_matches:
                # Handle IN clause expansion
                for param_name in postcompile_matches:
                    param_value = processed_params.get(param_name)
                    if isinstance(param_value, list):
                        # Expand the list into individual placeholders
                        placeholders = ", ".join(["%s"] * len(param_value))
                        query = query.replace(f"__[POSTCOMPILE_{param_name}]", placeholders)
                        # Add the list values to our params to process
                        # Store them separately so we can build the param tuple correctly
                        processed_params[f"_expanded_{param_name}"] = param_value

                # Now build the parameter tuple with expanded values
                param_values = []
                for param_name in postcompile_matches:
                    expanded_key = f"_expanded_{param_name}"
                    if expanded_key in processed_params:
                        param_values.extend(processed_params[expanded_key])
                param_values = tuple(param_values)
            else:
                # SQLAlchemy's pymysql dialect uses %(param_name)s format
                param_pattern = re.compile(r"%\(([^)]+)\)s")
                param_matches = param_pattern.findall(query)

                logger.debug(f"[{self.name}] Found parameters in query: {param_matches}")

                # Build tuple of values in the correct order
                if param_matches:
                    param_values = tuple(processed_params.get(name) for name in param_matches)
                    # Replace %(name)s with %s
                    query = param_pattern.sub("%s", query)
                elif processed_params:
                    # If no named parameters found, but we have params,
                    # the query might already be using %s placeholders
                    # In this case, we need to order params by their keys in the VALUES clause
                    # Extract column names from INSERT statement
                    insert_match = re.search(r"INSERT INTO \w+ \(([^)]+)\)", query)
                    if insert_match:
                        columns = [col.strip() for col in insert_match.group(1).split(",")]
                        param_values = tuple(processed_params.get(col) for col in columns)
                    else:
                        # Fallback: use dict values in iteration order
                        param_values = tuple(processed_params.values())
                else:
                    param_values = None

            async with (
                self._get_connection() as connection,
                connection.cursor(aiomysql.DictCursor) as cursor,
            ):
                # Execute with positional parameters
                if param_values:
                    await cursor.execute(query, param_values)
                else:
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
            if "param_values" in locals():
                logger.error(f"[{self.name}] Param values: {param_values}")
            if "processed_params" in locals():
                logger.error(f"[{self.name}] Processed params: {processed_params}")

            # Additional context for foreign key violations
            error_str = str(e).lower()
            if "foreign key" in error_str or "constraint" in error_str:
                logger.error(
                    f"[{self.name}] FOREIGN KEY CONSTRAINT VIOLATION detected! "
                    f"This typically means a referenced record doesn't exist in the parent table. "
                    f"Check that all foreign key references (e.g., meeting_id) exist before inserting."
                )

            raise
