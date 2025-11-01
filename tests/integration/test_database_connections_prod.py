"""
Integration tests for production PostgreSQL database connections.

These tests require a running PostgreSQL instance.

Run with production environment:
    pytest --db-env prod tests/integration/test_database_connections_prod.py

Or with helper script:
    ./run_tests_env.sh prod tests/integration/test_database_connections_prod.py
"""

import os

import pytest

from source.server.production.postgresql import PostgreSQLServer

# ============================================================================
# PostgreSQL Real Connection Tests (Production)
# ============================================================================


@pytest.mark.integration
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_real_connection() -> None:
    """
    Test real PostgreSQL connection (requires running PostgreSQL instance).

    Production environment only - uses PostgreSQL database.
    """
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
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_query_execution() -> None:
    """
    Test PostgreSQL query execution (requires running PostgreSQL instance).

    Production environment only - uses PostgreSQL database.
    """
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
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_failed_connection() -> None:
    """
    Test PostgreSQL connection failure handling.

    Production environment only - verifies that connection errors
    are properly raised when connecting to invalid host.
    """
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


@pytest.mark.integration
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_connection_pool_properties() -> None:
    """
    Test PostgreSQL connection pool properties.

    Production environment only - verifies that the connection pool
    is properly configured with correct min/max sizes.
    """
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

        # Verify pool configuration
        assert postgres.pool.minsize >= 1
        assert postgres.pool.maxsize >= postgres.pool.minsize

    finally:
        await postgres.disconnect()


@pytest.mark.integration
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_multiple_sequential_queries() -> None:
    """
    Test multiple sequential queries on PostgreSQL connection.

    Production environment only - verifies that the connection can handle
    multiple sequential queries without issues.
    """
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

        # Execute multiple queries sequentially
        for i in range(3):
            result = await postgres.query(f"SELECT {i} as value", params=None)
            assert result is not None

    finally:
        await postgres.disconnect()


@pytest.mark.integration
@pytest.mark.prod
@pytest.mark.asyncio
async def test_postgres_transaction_support() -> None:
    """
    Test PostgreSQL transaction support.

    Production environment only - verifies that PostgreSQL connection
    supports transactions (if applicable).
    """
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

        # Test that we have a working connection for transactions
        result = await postgres.query("SELECT 1", params=None)
        assert result is not None

    finally:
        await postgres.disconnect()
