"""
Unit tests for PostgreSQL server connection handling.

Tests verify that the PostgreSQL handler can:
- Connect and disconnect properly
- Perform health checks
- Handle connection errors gracefully
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import AsyncGenerator

from source.server.production.postgresql import PostgreSQLServer


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def postgres_config() -> dict:
    """Provide PostgreSQL configuration for testing."""
    return {
        "name": "test_postgres",
        "host": "localhost",
        "port": 5432,
        "user": "postgres",
        "password": "test_password",
        "database": "test_db",
    }


@pytest.fixture
def postgres_server(postgres_config: dict) -> PostgreSQLServer:
    """Create a PostgreSQL server instance for testing."""
    return PostgreSQLServer(**postgres_config)


# ============================================================================
# Connection Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_initialization_with_individual_params(
    postgres_config: dict,
) -> None:
    """Test PostgreSQL server initialization with individual parameters."""
    server = PostgreSQLServer(**postgres_config)

    assert server.name == "test_postgres"
    assert server.host == "localhost"
    assert server.port == 5432
    assert server.database == "test_db"
    assert "postgresql://" in server.connection_string


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_initialization_with_connection_string() -> None:
    """Test PostgreSQL server initialization with connection string."""
    connection_string = "postgresql://user:pass@host:5432/db"
    server = PostgreSQLServer(
        name="test_postgres",
        connection_string=connection_string,
    )

    assert server.name == "test_postgres"
    assert server.connection_string == connection_string


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_connect_success(postgres_server: PostgreSQLServer) -> None:
    """Test successful PostgreSQL connection establishment."""
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()

    with patch("asyncpg.create_pool", return_value=mock_pool) as mock_create:
        await postgres_server.connect()

        mock_create.assert_called_once()
        assert postgres_server.pool is not None
        assert postgres_server._connected is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_connect_failure(postgres_server: PostgreSQLServer) -> None:
    """Test PostgreSQL connection failure handling."""
    with patch(
        "asyncpg.create_pool",
        side_effect=Exception("Connection failed"),
    ):
        with pytest.raises(Exception, match="Connection failed"):
            await postgres_server.connect()

        assert postgres_server._connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_disconnect_success(postgres_server: PostgreSQLServer) -> None:
    """Test successful PostgreSQL disconnection."""
    mock_pool = AsyncMock()
    postgres_server.pool = mock_pool
    postgres_server._connected = True

    await postgres_server.disconnect()

    mock_pool.close.assert_called_once()
    assert postgres_server._connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_disconnect_without_pool(
    postgres_server: PostgreSQLServer,
) -> None:
    """Test disconnection when pool doesn't exist."""
    postgres_server.pool = None
    postgres_server._connected = False

    # Should not raise an error
    await postgres_server.disconnect()
    assert postgres_server._connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_disconnect_failure(postgres_server: PostgreSQLServer) -> None:
    """Test PostgreSQL disconnection failure handling."""
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock(side_effect=Exception("Disconnect failed"))
    postgres_server.pool = mock_pool
    postgres_server._connected = True

    with pytest.raises(Exception, match="Disconnect failed"):
        await postgres_server.disconnect()


# ============================================================================
# Health Check Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_health_check_healthy(postgres_server: PostgreSQLServer) -> None:
    """Test successful PostgreSQL health check."""
    mock_connection = AsyncMock()
    mock_connection.fetchval = AsyncMock(return_value=1)

    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    postgres_server.pool = mock_pool

    result = await postgres_server.health_check()

    assert result is True
    mock_connection.fetchval.assert_called_once_with("SELECT 1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_health_check_unhealthy(
    postgres_server: PostgreSQLServer,
) -> None:
    """Test failed PostgreSQL health check with incorrect response."""
    mock_connection = AsyncMock()
    mock_connection.fetchval = AsyncMock(return_value=0)

    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    postgres_server.pool = mock_pool

    result = await postgres_server.health_check()

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_health_check_no_pool(postgres_server: PostgreSQLServer) -> None:
    """Test health check when pool is not initialized."""
    postgres_server.pool = None

    result = await postgres_server.health_check()

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_health_check_exception(
    postgres_server: PostgreSQLServer,
) -> None:
    """Test health check exception handling."""
    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(side_effect=Exception("Pool error"))
    postgres_server.pool = mock_pool

    result = await postgres_server.health_check()

    assert result is False


# ============================================================================
# Connection Pool Management Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_get_connection_success(
    postgres_server: PostgreSQLServer,
) -> None:
    """Test successful connection retrieval from pool."""
    mock_connection = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    mock_pool.release = AsyncMock()

    postgres_server.pool = mock_pool

    async with postgres_server._get_connection() as conn:
        assert conn == mock_connection

    mock_pool.acquire.assert_called_once()
    mock_pool.release.assert_called_once_with(mock_connection)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_get_connection_no_pool(
    postgres_server: PostgreSQLServer,
) -> None:
    """Test connection retrieval when pool is not initialized."""
    postgres_server.pool = None

    with pytest.raises(RuntimeError, match="Connection pool not initialized"):
        async with postgres_server._get_connection():
            pass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_get_connection_exception_handling(
    postgres_server: PostgreSQLServer,
) -> None:
    """Test connection release after exception."""
    mock_connection = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    mock_pool.release = AsyncMock()

    postgres_server.pool = mock_pool

    with pytest.raises(ValueError):
        async with postgres_server._get_connection():
            raise ValueError("Test error")

    # Connection should still be released
    mock_pool.release.assert_called_once_with(mock_connection)


# ============================================================================
# Connection String Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_connection_string_format(
    postgres_server: PostgreSQLServer,
) -> None:
    """Test PostgreSQL connection string format."""
    assert postgres_server.connection_string.startswith("postgresql://")
    assert "localhost" in postgres_server.connection_string
    assert "5432" in postgres_server.connection_string
    assert "test_db" in postgres_server.connection_string


@pytest.mark.unit
def test_postgres_env_variable_fallback() -> None:
    """Test PostgreSQL using environment variables as fallback."""
    import os

    # Set environment variables
    os.environ["POSTGRES_HOST"] = "env_host"
    os.environ["POSTGRES_PORT"] = "5433"
    os.environ["POSTGRES_USER"] = "env_user"
    os.environ["POSTGRES_PASSWORD"] = "env_pass"
    os.environ["POSTGRES_DB"] = "env_db"

    try:
        server = PostgreSQLServer(name="test_server")

        assert server.host == "env_host"
        assert server.port == 5433
        assert server.database == "env_db"
    finally:
        # Clean up environment variables
        for key in [
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_DB",
        ]:
            if key in os.environ:
                del os.environ[key]
