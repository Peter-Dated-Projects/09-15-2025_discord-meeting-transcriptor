"""
Unit tests for MySQL server connection handling.

Tests verify that the MySQL handler can:
- Connect and disconnect properly
- Perform health checks
- Handle connection errors gracefully
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from source.server.dev.mysql import MySQLServer

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mysql_config() -> dict:
    """Provide MySQL configuration for testing."""
    return {
        "name": "test_mysql",
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "test_password",
        "database": "test_db",
    }


@pytest.fixture
def mysql_server(mysql_config: dict) -> MySQLServer:
    """Create a MySQL server instance for testing."""
    return MySQLServer(**mysql_config)


# ============================================================================
# Connection Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_initialization_with_individual_params(
    mysql_config: dict,
) -> None:
    """Test MySQL server initialization with individual parameters."""
    server = MySQLServer(**mysql_config)

    assert server.name == "test_mysql"
    assert server.host == "localhost"
    assert server.port == 3306
    assert server.database == "test_db"
    assert "mysql://" in server.connection_string


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_initialization_with_connection_string() -> None:
    """Test MySQL server initialization with connection string."""
    connection_string = "mysql://user:pass@host:3306/db"
    server = MySQLServer(
        name="test_mysql",
        connection_string=connection_string,
    )

    assert server.name == "test_mysql"
    assert server.connection_string == connection_string


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_connect_success(mysql_server: MySQLServer) -> None:
    """Test successful MySQL connection establishment."""
    mock_pool = AsyncMock()
    mock_pool.close = AsyncMock()

    async def mock_create_pool(*_args: object, **_kwargs: object) -> AsyncMock:
        return mock_pool

    with patch("aiomysql.create_pool", side_effect=mock_create_pool) as mock_create:
        await mysql_server.connect()

        mock_create.assert_called_once()
        assert mysql_server.pool is not None
        assert mysql_server._connected is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_connect_failure(mysql_server: MySQLServer) -> None:
    """Test MySQL connection failure handling."""
    with patch(
        "aiomysql.create_pool",
        side_effect=Exception("Connection failed"),
    ):
        with pytest.raises(Exception, match="Connection failed"):
            await mysql_server.connect()

        assert mysql_server._connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_disconnect_success(mysql_server: MySQLServer) -> None:
    """Test successful MySQL disconnection."""
    mock_pool = AsyncMock()
    mock_pool.close = MagicMock()
    mock_pool.wait_closed = AsyncMock()

    mysql_server.pool = mock_pool
    mysql_server._connected = True

    await mysql_server.disconnect()

    mock_pool.close.assert_called_once()
    mock_pool.wait_closed.assert_called_once()
    assert mysql_server._connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_disconnect_without_pool(mysql_server: MySQLServer) -> None:
    """Test disconnection when pool doesn't exist."""
    mysql_server.pool = None
    mysql_server._connected = False

    # Should not raise an error
    await mysql_server.disconnect()
    assert mysql_server._connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_disconnect_failure(mysql_server: MySQLServer) -> None:
    """Test MySQL disconnection failure handling."""
    mock_pool = AsyncMock()
    mock_pool.close = MagicMock(side_effect=Exception("Disconnect failed"))
    mysql_server.pool = mock_pool
    mysql_server._connected = True

    with pytest.raises(Exception, match="Disconnect failed"):
        await mysql_server.disconnect()


# ============================================================================
# Health Check Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_health_check_healthy(mysql_server: MySQLServer) -> None:
    """Test successful MySQL health check."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(1,))

    mock_connection = AsyncMock()

    # Create a proper async context manager for cursor
    @asynccontextmanager
    async def cursor_context_manager():
        yield mock_cursor

    mock_connection.cursor = cursor_context_manager

    # Create a context manager that returns the connection
    @asynccontextmanager
    async def pool_acquire_context_manager():
        yield mock_connection

    mock_pool = AsyncMock()
    mock_pool.acquire = pool_acquire_context_manager
    mysql_server.pool = mock_pool

    result = await mysql_server.health_check()

    assert result is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_health_check_unhealthy(mysql_server: MySQLServer) -> None:
    """Test failed MySQL health check with incorrect response."""
    mock_cursor = AsyncMock()
    mock_cursor.execute = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=None)

    mock_connection = AsyncMock()
    mock_connection.cursor = MagicMock(return_value=mock_cursor)

    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    mysql_server.pool = mock_pool

    result = await mysql_server.health_check()

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_health_check_no_pool(mysql_server: MySQLServer) -> None:
    """Test health check when pool is not initialized."""
    mysql_server.pool = None

    result = await mysql_server.health_check()

    assert result is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_health_check_exception(mysql_server: MySQLServer) -> None:
    """Test health check exception handling."""
    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(side_effect=Exception("Pool error"))
    mysql_server.pool = mock_pool

    result = await mysql_server.health_check()

    assert result is False


# ============================================================================
# Connection Pool Management Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_get_connection_success(mysql_server: MySQLServer) -> None:
    """Test successful connection retrieval from pool."""
    mock_connection = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    mock_pool.release = MagicMock()

    mysql_server.pool = mock_pool

    async with mysql_server._get_connection() as conn:
        assert conn == mock_connection

    mock_pool.acquire.assert_called_once()
    mock_pool.release.assert_called_once_with(mock_connection)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_get_connection_no_pool(mysql_server: MySQLServer) -> None:
    """Test connection retrieval when pool is not initialized."""
    mysql_server.pool = None

    with pytest.raises(RuntimeError, match="Connection pool not initialized"):
        async with mysql_server._get_connection():
            pass


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_get_connection_exception_handling(
    mysql_server: MySQLServer,
) -> None:
    """Test connection release after exception."""
    mock_connection = AsyncMock()
    mock_pool = AsyncMock()
    mock_pool.acquire = AsyncMock(return_value=mock_connection)
    mock_pool.release = MagicMock()

    mysql_server.pool = mock_pool

    with pytest.raises(ValueError):
        async with mysql_server._get_connection():
            raise ValueError("Test error")

    # Connection should still be released
    mock_pool.release.assert_called_once_with(mock_connection)


# ============================================================================
# Connection String Tests
# ============================================================================


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mysql_connection_string_format(mysql_server: MySQLServer) -> None:
    """Test MySQL connection string format."""
    assert mysql_server.connection_string.startswith("mysql://")
    assert "localhost" in mysql_server.connection_string
    assert "3306" in mysql_server.connection_string
    assert "test_db" in mysql_server.connection_string


@pytest.mark.unit
def test_mysql_env_variable_fallback() -> None:
    """Test MySQL using environment variables as fallback."""
    import os

    # Set environment variables
    os.environ["MYSQL_HOST"] = "env_host"
    os.environ["MYSQL_PORT"] = "3307"
    os.environ["MYSQL_USER"] = "env_user"
    os.environ["MYSQL_PASSWORD"] = "env_pass"
    os.environ["MYSQL_DB"] = "env_db"

    try:
        server = MySQLServer(name="test_server")

        assert server.host == "env_host"
        assert server.port == 3307
        assert server.database == "env_db"
    finally:
        # Clean up environment variables
        for key in [
            "MYSQL_HOST",
            "MYSQL_PORT",
            "MYSQL_USER",
            "MYSQL_PASSWORD",
            "MYSQL_DB",
        ]:
            if key in os.environ:
                del os.environ[key]
