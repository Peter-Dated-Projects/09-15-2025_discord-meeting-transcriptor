"""
Pytest configuration and shared fixtures.

This file is automatically loaded by pytest and provides
fixtures and configuration that can be used across all tests.
"""

import asyncio
import os
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)


# ============================================================================
# Environment Detection and Validation
# ============================================================================


# ---------------------------------------------------------------------------
# Backwards-compatibility: map legacy SQL_* env vars to MYSQL_* and POSTGRES_*
# If the repository .env or CI uses SQL_HOST/SQL_PORT/SQL_USER/SQL_PASSWORD/SQL_DB
# we'll propagate those values to MYSQL_* and POSTGRES_* env vars so tests
# (which read MYSQL_*/POSTGRES_*) work without editing many files.
# ---------------------------------------------------------------------------


def _map_sql_env_to_db_prefixes() -> None:
    """Map SQL_* env vars to MYSQL_* and POSTGRES_* if not already present."""
    keys = ["HOST", "PORT", "DB", "USER", "PASSWORD"]
    for k in keys:
        sql_key = f"SQL_{k}"
        val = os.getenv(sql_key)
        if val is None:
            continue

        mysql_key = f"MYSQL_{k}"
        pg_key = f"POSTGRES_{k}"

        # Only set if target not already defined (don't overwrite explicit values)
        if os.getenv(mysql_key) is None:
            os.environ[mysql_key] = val
        if os.getenv(pg_key) is None:
            os.environ[pg_key] = val


_map_sql_env_to_db_prefixes()


def get_test_env(config: pytest.Config | None = None) -> str:
    """
    Determine the test environment (local or prod).

    REQUIRED: Users must specify either --db-env local or --db-env prod

    Args:
        config: pytest Config object (used to get --db-env option)

    Returns:
        str: 'local' (uses MySQL) or 'prod' (uses PostgreSQL)

    Raises:
        ValueError: If neither --db-env local nor --db-env prod is specified
    """
    # First check for command-line option
    if config is not None and hasattr(config.option, "db_env"):
        env = config.option.db_env
        if env:
            return env

    # Fall back to environment variable for backwards compatibility
    env = os.getenv("TEST_ENV", "").lower()
    if env in ("local", "prod"):
        return env

    # Not found - raise error
    raise ValueError(
        "\n"
        "❌ TEST ENVIRONMENT NOT SPECIFIED\n"
        "\n"
        "You must specify which test environment to use. Choose one:\n"
        "\n"
        "  Local (MySQL):\n"
        "    pytest --db-env local\n"
        "\n"
        "  Production (PostgreSQL):\n"
        "    pytest --db-env prod\n"
        "\n"
        "Or use environment variables:\n"
        "    TEST_ENV=local pytest\n"
        "    TEST_ENV=prod pytest\n"
        "\n"
        "Examples:\n"
        "  pytest --db-env local tests/unit\n"
        "  pytest --db-env prod tests/integration\n"
        "  TEST_ENV=local pytest -m 'not integration'\n"
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command-line options to pytest."""
    parser.addoption(
        "--db-env",
        action="store",
        default=None,
        choices=["local", "prod"],
        help="Required: Specify database environment. "
        "Choose 'local' (MySQL) or 'prod' (PostgreSQL). "
        "Alternatively, set TEST_ENV environment variable.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom settings and markers."""
    # Validate that environment is specified
    try:
        env = get_test_env(config)
    except ValueError as e:
        # Store the error to raise it during collection
        config.db_env_error = str(e)
        config.db_env = None
        return

    config.db_env = env

    # Register markers
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "local: Local/dev environment tests (uses MySQL)")
    config.addinivalue_line("markers", "prod: Production environment tests (uses PostgreSQL)")


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """
    Modify test collection based on the database environment.

    Filters tests based on environment markers:
    - --db-env local or TEST_ENV=local: Skip tests marked with @pytest.mark.prod
    - --db-env prod or TEST_ENV=prod: Skip tests marked with @pytest.mark.local

    Raises:
        pytest.UsageError: If environment is not specified
    """
    # Check if environment was already validated and errored
    if hasattr(config, "db_env_error") and config.db_env_error:
        raise pytest.UsageError(config.db_env_error)

    try:
        test_env = get_test_env(config)
    except ValueError as e:
        raise pytest.UsageError(str(e))

    skip_marker = pytest.mark.skip(reason=f"Skipped for {test_env} environment")

    for item in items:
        # Skip prod tests when running local
        if test_env == "local" and "prod" in item.keywords:
            item.add_marker(skip_marker)

        # Skip local tests when running prod
        if test_env == "prod" and "local" in item.keywords:
            item.add_marker(skip_marker)


# ============================================================================
# Pytest Configuration
# ============================================================================


@pytest.fixture(scope="session")
def test_environment(request: pytest.FixtureRequest) -> str:
    """
    Get the current test environment (local or prod).

    REQUIRED: Must be specified via --db-env or TEST_ENV
    """
    try:
        env = get_test_env(request.config)
        return env
    except ValueError as e:
        pytest.fail(str(e))


# ============================================================================
# Async Fixtures
# ============================================================================


@pytest.fixture
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================================
# Mock Discord Fixtures
# ============================================================================


@pytest.fixture
def mock_discord_bot() -> MagicMock:
    """Create a mock Discord bot instance."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.name = "TestBot"
    bot.user.id = 123456789
    bot.guilds = []
    return bot


@pytest.fixture
def mock_discord_interaction() -> MagicMock:
    """Create a mock Discord interaction."""
    interaction = MagicMock()
    interaction.user = MagicMock()
    interaction.user.name = "TestUser"
    interaction.user.id = 987654321
    interaction.user.voice = None
    interaction.guild = MagicMock()
    interaction.guild.id = 111222333
    interaction.guild.name = "Test Guild"
    interaction.response = AsyncMock()
    return interaction


@pytest.fixture
def mock_voice_channel() -> MagicMock:
    """Create a mock Discord voice channel."""
    channel = MagicMock()
    channel.id = 444555666
    channel.name = "Test Voice Channel"
    channel.guild = MagicMock()
    channel.connect = AsyncMock()
    return channel


@pytest.fixture
def mock_discord_user_in_voice(
    mock_discord_interaction: MagicMock,
    mock_voice_channel: MagicMock,
) -> MagicMock:
    """Create a mock Discord user in a voice channel."""
    mock_discord_interaction.user.voice = MagicMock()
    mock_discord_interaction.user.voice.channel = mock_voice_channel
    return mock_discord_interaction


# ============================================================================
# Database Fixtures - Environment-Aware
# ============================================================================


@pytest.fixture
def database_server(test_environment: str):
    """
    Provide the appropriate database server based on environment.

    Returns the correct server handler class:
    - 'local': MySQLServer
    - 'prod': PostgreSQLServer

    NOTE: test_environment is REQUIRED and will fail if not specified
    """
    if test_environment == "prod":
        from source.server.production.postgresql import PostgreSQLServer

        return PostgreSQLServer
    elif test_environment == "local":
        from source.server.dev.mysql import MySQLServer

        return MySQLServer
    else:
        pytest.fail(f"Invalid test environment: {test_environment}")


@pytest.fixture
def database_config(test_environment: str) -> dict:
    """
    Provide database configuration based on environment.

    Returns configuration for either local (MySQL) or prod (PostgreSQL) database.

    NOTE: test_environment is REQUIRED and will fail if not specified
    """
    if test_environment == "prod":
        return {
            "name": "test_postgres",
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", "5432")),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
            "database": os.getenv("POSTGRES_DB", "test_db"),
        }
    elif test_environment == "local":
        return {
            "name": "test_mysql",
            "host": os.getenv("MYSQL_HOST", "localhost"),
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "user": os.getenv("MYSQL_USER", "root"),
            "password": os.getenv("MYSQL_PASSWORD", "test_password"),
            "database": os.getenv("MYSQL_DB", "test_db"),
        }
    else:
        pytest.fail(f"Invalid test environment: {test_environment}")


@pytest.fixture
async def database_connection(database_server, database_config):
    """
    Create a real database connection for the current environment.

    Yields a connected database server instance. Useful for integration tests.
    """
    server = database_server(**database_config)
    await server.connect()
    yield server
    await server.disconnect()


# ============================================================================
# Mock Database Fixtures
# ============================================================================


@pytest.fixture
async def mock_postgres_pool() -> AsyncMock:
    """Create a mock PostgreSQL connection pool."""
    pool = AsyncMock()
    pool.acquire = AsyncMock()
    pool.release = AsyncMock()
    pool.close = AsyncMock()
    return pool


@pytest.fixture
async def mock_postgres_connection() -> AsyncMock:
    """Create a mock PostgreSQL connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetchval = AsyncMock(return_value=None)
    conn.close = AsyncMock()
    return conn


@pytest.fixture
async def mock_mysql_pool() -> AsyncMock:
    """Create a mock MySQL connection pool."""
    pool = AsyncMock()
    pool.acquire = AsyncMock()
    pool.release = AsyncMock()
    pool.close = AsyncMock()
    return pool


@pytest.fixture
async def mock_mysql_connection() -> AsyncMock:
    """Create a mock MySQL connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchall = AsyncMock(return_value=[])
    conn.fetchone = AsyncMock(return_value=None)
    conn.close = AsyncMock()
    return conn


# ============================================================================
# Service Fixtures
# ============================================================================


@pytest.fixture
def sample_transcript() -> str:
    """Provide a sample transcript for testing."""
    return """
    [Speaker1 00:00]: Welcome everyone to today's meeting.
    [Speaker2 00:15]: Thanks for having me. Let's discuss the project timeline.
    [Speaker1 00:30]: Agreed. We need to finish phase one by next week.
    [Speaker2 00:45]: I think that's doable if we prioritize the core features.
    [Speaker1 01:00]: Perfect. Let's also talk about the budget.
    """


@pytest.fixture
def sample_meeting_id() -> str:
    """Provide a sample meeting ID."""
    return "meeting_2025_10_16_001"


# ============================================================================
# Cleanup Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def cleanup_after_test() -> Generator[None, None, None]:
    """Automatically cleanup after each test."""
    yield
    # Add any cleanup logic here if needed
    pass
