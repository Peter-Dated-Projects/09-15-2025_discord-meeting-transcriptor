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
        "❌ TEST ENVIRONMENT NOT SPECIFIED FOR INTEGRATION TESTS\n"
        "\n"
        "Integration tests require a database environment. Choose one:\n"
        "\n"
        "  Local (MySQL):\n"
        "    pytest --db-env local tests/integration\n"
        "\n"
        "  Production (PostgreSQL):\n"
        "    pytest --db-env prod tests/integration\n"
        "\n"
        "Or use environment variables:\n"
        "    TEST_ENV=local pytest tests/integration\n"
        "    TEST_ENV=prod pytest tests/integration\n"
        "\n"
        "Note: Unit tests do not require --db-env:\n"
        "    pytest tests/unit  # No --db-env needed\n"
        "    pytest -m unit     # No --db-env needed\n"
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command-line options to pytest."""
    parser.addoption(
        "--db-env",
        action="store",
        default=None,
        choices=["local", "prod"],
        help="Specify database environment (required for integration tests). "
        "Choose 'local' (MySQL) or 'prod' (PostgreSQL). "
        "Unit tests do not require this flag. "
        "Alternatively, set TEST_ENV environment variable.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom settings and markers."""
    # Try to get environment, but don't fail here - will validate later for integration tests
    try:
        env = get_test_env(config)
        config.db_env = env
        config.db_env_error = None
    except ValueError as e:
        # Store the error but don't fail yet - we'll check in pytest_collection_modifyitems
        # to see if we actually need the environment (i.e., if we have integration tests)
        config.db_env_error = str(e)
        config.db_env = None

    # Register markers (always do this regardless of environment)
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

    For unit tests (marked with @pytest.mark.unit), environment is optional.
    For integration tests, environment is required.

    Raises:
        pytest.UsageError: If environment is not specified for integration tests
    """
    # Check if any integration tests are in the collection
    has_integration_tests = any("integration" in item.keywords for item in items)
    has_only_unit_tests = all("unit" in item.keywords for item in items)

    # If only unit tests are being run, environment is optional
    if has_only_unit_tests:
        # Apply timeout to all tests except those marked as slow
        for item in items:
            if "slow" not in item.keywords:
                item.add_marker(pytest.mark.timeout(30))
        return

    # For integration tests or mixed tests, require environment
    if hasattr(config, "db_env_error") and config.db_env_error:
        raise pytest.UsageError(config.db_env_error)

    try:
        test_env = get_test_env(config)
    except ValueError as e:
        # Only raise error if we have integration tests
        if has_integration_tests:
            raise pytest.UsageError(str(e))
        else:
            # No integration tests, environment not needed
            test_env = None

    if test_env:
        skip_marker = pytest.mark.skip(reason=f"Skipped for {test_env} environment")

        for item in items:
            # Skip prod tests when running local
            if test_env == "local" and "prod" in item.keywords:
                item.add_marker(skip_marker)

            # Skip local tests when running prod
            if test_env == "prod" and "local" in item.keywords:
                item.add_marker(skip_marker)

    # Apply timeout to all tests except those marked as slow
    for item in items:
        if "slow" not in item.keywords:
            item.add_marker(pytest.mark.timeout(30))


# ============================================================================
# Pytest Configuration
# ============================================================================


@pytest.fixture(scope="session")
def test_environment(request: pytest.FixtureRequest) -> str:
    """
    Get the current test environment (local or prod).

    REQUIRED for integration tests, optional for unit tests.
    """
    try:
        env = get_test_env(request.config)
        return env
    except ValueError:
        # If no environment is specified, default to 'local' for unit tests
        # Integration tests will fail earlier in pytest_collection_modifyitems
        return "local"


@pytest.fixture(scope="session")
def shared_test_log_file(tmp_path_factory) -> str:
    """
    Create a single shared log file for all tests in the session.

    This prevents creating a new timestamped log file for each test,
    consolidating all test logs into one file for easier debugging.

    Returns:
        str: Path to the shared log file
    """
    from datetime import datetime

    # Create a logs directory in the test temp directory
    logs_dir = tmp_path_factory.mktemp("logs")

    # Create a single log file with timestamp in the name
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"test_run_{timestamp}.log"

    return str(log_file)


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
def mock_discord_context() -> MagicMock:
    """Create a mock Discord application context (py-cord)."""
    ctx = MagicMock()
    ctx.author = MagicMock()
    ctx.author.name = "TestUser"
    ctx.author.id = 987654321
    ctx.author.voice = None
    ctx.guild = MagicMock()
    ctx.guild.id = 111222333
    ctx.guild.name = "Test Guild"
    ctx.defer = AsyncMock()
    ctx.respond = AsyncMock()
    ctx.edit = AsyncMock()
    ctx.followup = MagicMock()
    ctx.followup.send = AsyncMock()
    return ctx


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
    mock_discord_context: MagicMock,
    mock_voice_channel: MagicMock,
) -> MagicMock:
    """Create a mock Discord user in a voice channel."""
    mock_discord_context.author.voice = MagicMock()
    mock_discord_context.author.voice.channel = mock_voice_channel
    return mock_discord_context


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


# ============================================================================
# Testing Environment Fixtures (for unit tests with in-memory databases)
# ============================================================================


@pytest.fixture
async def test_context():
    """
    Create a test context instance.

    This fixture provides a Context instance for testing.

    Yields:
        Context: Test context instance
    """
    from source.context import Context

    context = Context()
    yield context


@pytest.fixture
async def test_server_manager(test_context):
    """
    Create and connect a test server manager with in-memory databases.

    This fixture provides a ServerManager instance with:
    - In-memory SQLite database (mimics MySQL)
    - In-memory ChromaDB
    - Real Whisper server client (uses common implementation)

    Ideal for unit tests that need database access without external dependencies.
    Note: Whisper server tests will require a running Whisper server or additional mocking.

    Args:
        test_context: Test context from test_context fixture

    Yields:
        ServerManager: Connected test server manager instance
    """
    from source.constructor import ServerManagerType
    from source.server.constructor import construct_server_manager

    server = construct_server_manager(ServerManagerType.TESTING, test_context)
    test_context.set_server_manager(server)
    await server.connect_all()

    yield server

    await server.disconnect_all()


@pytest.fixture
async def test_sql_client(test_server_manager):
    """
    Get the in-memory SQL client from test server manager.

    Args:
        test_server_manager: Test server manager fixture

    Yields:
        InMemoryMySQLServer: In-memory SQL database client
    """
    yield test_server_manager.sql_client


@pytest.fixture
async def test_vector_db_client(test_server_manager):
    """
    Get the in-memory ChromaDB client from test server manager.

    Args:
        test_server_manager: Test server manager fixture

    Yields:
        InMemoryChromaDBClient: In-memory vector database client
    """
    yield test_server_manager.vector_db_client


@pytest.fixture
async def test_whisper_client(test_server_manager):
    """
    Get the Whisper server client from test server manager.

    Args:
        test_server_manager: Test server manager fixture

    Yields:
        WhisperServerClient: Whisper server client (uses common implementation)
    """
    yield test_server_manager.whisper_server_client


# ============================================================================
# Shared Server and Services Fixtures (for integration tests)
# ============================================================================


@pytest.fixture
def _test_environment(test_environment: str) -> str:
    """
    Internal fixture to pass test_environment to other fixtures.

    This is a workaround for fixtures that need test_environment but
    are used in integration tests. The underscore prefix indicates
    it's an internal fixture.
    """
    return test_environment


@pytest.fixture
async def server_manager(_test_environment: str):
    """
    Create and connect a server manager for the current test environment.

    This fixture provides a fully connected ServerManager instance
    that can be used across integration tests. It automatically handles
    cleanup on teardown.

    Args:
        _test_environment: The test environment (local or prod)

    Yields:
        ServerManager: Connected server manager instance
    """
    from source.constructor import ServerManagerType
    from source.context import Context
    from source.server.constructor import construct_server_manager

    # Map test environment to ServerManagerType
    server_type = (
        ServerManagerType.DEVELOPMENT
        if _test_environment == "local"
        else ServerManagerType.PRODUCTION
    )

    # Create context
    context = Context()

    server = construct_server_manager(server_type, context)
    context.set_server_manager(server)
    await server.connect_all()

    yield server

    await server.disconnect_all()


@pytest.fixture
async def services_manager(server_manager, tmp_path, shared_test_log_file):
    """
    Create and initialize a services manager with temporary storage.

    This fixture provides a fully initialized ServicesManager instance
    with all services ready to use. It uses temporary directories for
    storage to ensure test isolation.

    Args:
        server_manager: Connected server manager from server_manager fixture
        tmp_path: Pytest's built-in temporary directory fixture
        shared_test_log_file: Session-scoped shared log file path

    Yields:
        ServicesManager: Initialized services manager instance
    """
    from source.constructor import ServerManagerType
    from source.services.constructor import construct_services_manager

    # Create temporary storage paths
    storage_path = str(tmp_path / "data")
    recording_storage_path = str(tmp_path / "data" / "recordings")
    transcription_storage_path = str(tmp_path / "data" / "transcriptions")
    conversation_storage_path = str(tmp_path / "data" / "conversations")

    # Determine server type from server_manager
    # This is a bit of a hack, but it works for both dev and prod
    server_type = (
        ServerManagerType.DEVELOPMENT
        if hasattr(server_manager, "mysql_server")
        else ServerManagerType.PRODUCTION
    )

    # Get context from server_manager
    context = server_manager.context

    services = construct_services_manager(
        service_type=server_type,
        context=context,
        storage_path=storage_path,
        recording_storage_path=recording_storage_path,
        transcription_storage_path=transcription_storage_path,
        conversation_storage_path=conversation_storage_path,
        log_file=shared_test_log_file,  # Use shared log file
        use_timestamp_logs=False,  # Don't create timestamp-based logs
    )

    await services.initialize_all()

    yield services

    # Cleanup is handled by the services manager itself
    # No explicit teardown needed
