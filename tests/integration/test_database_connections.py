"""
Integration tests for database connections.

These tests require actual database instances to be running.
Mark with @pytest.mark.integration to skip during unit test runs.

Run with: pytest -m integration
"""

import pytest
import os
from typing import AsyncGenerator

from source.server.production.postgresql import PostgreSQLServer
from source.server.dev.mysql import MySQLServer


# ============================================================================
# PostgreSQL Integration Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_real_connection() -> None:
    """Test real PostgreSQL connection (requires running PostgreSQL instance)."""
    # Use environment variables or defaults
    postgres = PostgreSQLServer(
        name="integration_test_postgres",
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        database=os.getenv("POSTGRES_DB", "postgres"),
    )

    try:
        await postgres.connect()
        assert postgres.pool is not None
        assert postgres._connected is True

        # Test health check
        is_healthy = await postgres.health_check()
        assert is_healthy is True

    finally:
        await postgres.disconnect()
        assert postgres._connected is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_query_execution() -> None:
    """Test PostgreSQL query execution (requires running PostgreSQL instance)."""
    postgres = PostgreSQLServer(
        name="integration_test_postgres",
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        database=os.getenv("POSTGRES_DB", "postgres"),
    )

    try:
        await postgres.connect()

        # Execute a simple query
        result = await postgres.query("SELECT 1 as test_value", params=None)
        assert result is not None
        assert len(result) > 0

    finally:
        await postgres.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_failed_connection() -> None:
    """Test PostgreSQL connection failure handling."""
    postgres = PostgreSQLServer(
        name="integration_test_postgres",
        host="invalid_host_that_does_not_exist.local",
        port=5432,
        user="postgres",
        password="postgres",
        database="postgres",
    )

    with pytest.raises(Exception):
        await postgres.connect()

    assert postgres._connected is False


# ============================================================================
# MySQL Integration Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mysql_real_connection() -> None:
    """Test real MySQL connection (requires running MySQL instance)."""
    # Use environment variables or defaults
    mysql = MySQLServer(
        name="integration_test_mysql",
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DB", "mysql"),
    )

    try:
        await mysql.connect()
        assert mysql.pool is not None
        assert mysql._connected is True

        # Test health check
        is_healthy = await mysql.health_check()
        assert is_healthy is True

    finally:
        await mysql.disconnect()
        assert mysql._connected is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mysql_query_execution() -> None:
    """Test MySQL query execution (requires running MySQL instance)."""
    mysql = MySQLServer(
        name="integration_test_mysql",
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DB", "mysql"),
    )

    try:
        await mysql.connect()

        # Execute a simple query
        result = await mysql.query("SELECT 1 as test_value", params=None)
        assert result is not None
        assert len(result) > 0

    finally:
        await mysql.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mysql_failed_connection() -> None:
    """Test MySQL connection failure handling."""
    mysql = MySQLServer(
        name="integration_test_mysql",
        host="invalid_host_that_does_not_exist.local",
        port=3306,
        user="root",
        password="root",
        database="mysql",
    )

    with pytest.raises(Exception):
        await mysql.connect()

    assert mysql._connected is False


# ============================================================================
# Comparison Tests
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_and_mysql_independent_connections() -> None:
    """Test that PostgreSQL and MySQL can maintain independent connections."""
    postgres = PostgreSQLServer(
        name="integration_test_postgres",
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD", "postgres"),
        database=os.getenv("POSTGRES_DB", "postgres"),
    )

    mysql = MySQLServer(
        name="integration_test_mysql",
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "root"),
        database=os.getenv("MYSQL_DB", "mysql"),
    )

    try:
        await postgres.connect()
        await mysql.connect()

        pg_health = await postgres.health_check()
        mysql_health = await mysql.health_check()

        assert pg_health is True
        assert mysql_health is True
        assert postgres._connected is True
        assert mysql._connected is True

    finally:
        await postgres.disconnect()
        await mysql.disconnect()
