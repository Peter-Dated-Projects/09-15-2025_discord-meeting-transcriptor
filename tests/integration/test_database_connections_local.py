"""
Integration tests for local MySQL database connections.

These tests require a running MySQL instance.

Run with local environment:
    pytest --db-env local tests/integration/test_database_connections_local.py

Or with helper script:
    ./run_tests_env.sh local tests/integration/test_database_connections_local.py
"""

import pytest
import os
from typing import AsyncGenerator

from source.server.dev.mysql import MySQLServer


# ============================================================================
# MySQL Real Connection Tests (Local)
# ============================================================================


@pytest.mark.integration
@pytest.mark.local
@pytest.mark.asyncio
async def test_mysql_real_connection() -> None:
    """
    Test real MySQL connection (requires running MySQL instance).

    Local environment only - uses MySQL database.
    """
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
@pytest.mark.local
@pytest.mark.asyncio
async def test_mysql_query_execution() -> None:
    """
    Test MySQL query execution (requires running MySQL instance).

    Local environment only - uses MySQL database.
    """
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
@pytest.mark.local
@pytest.mark.asyncio
async def test_mysql_failed_connection() -> None:
    """
    Test MySQL connection failure handling.

    Local environment only - uses MySQL database.
    This test verifies that connection errors are properly raised.
    """
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


@pytest.mark.integration
@pytest.mark.local
@pytest.mark.asyncio
async def test_mysql_connection_pool_properties() -> None:
    """
    Test MySQL connection pool properties.

    Local environment only - verifies that the connection pool is properly
    configured with correct min/max sizes.
    """
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

        # Verify pool configuration
        assert mysql.pool.minsize >= 1
        assert mysql.pool.maxsize >= mysql.pool.minsize

    finally:
        await mysql.disconnect()


@pytest.mark.integration
@pytest.mark.local
@pytest.mark.asyncio
async def test_mysql_multiple_sequential_queries() -> None:
    """
    Test multiple sequential queries on MySQL connection.

    Local environment only - verifies that the connection can handle
    multiple sequential queries without issues.
    """
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

        # Execute multiple queries sequentially
        for i in range(3):
            result = await mysql.query(f"SELECT {i} as value", params=None)
            assert result is not None

    finally:
        await mysql.disconnect()
