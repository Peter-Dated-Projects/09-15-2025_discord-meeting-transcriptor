"""
Pytest configuration and shared fixtures.

This file is automatically loaded by pytest and provides
fixtures and configuration that can be used across all tests.
"""

import pytest
import asyncio
from typing import Generator, AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest with custom settings."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow running tests")


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
# Database Fixtures
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
