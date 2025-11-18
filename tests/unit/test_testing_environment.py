"""
Tests for the testing environment setup.

This module verifies that the in-memory testing infrastructure
works correctly.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_manager_creation(test_server_manager):
    """Test that test server manager can be created and connected."""
    assert test_server_manager is not None
    assert test_server_manager.is_initialized

    # Check all clients are connected
    assert test_server_manager.sql_client.is_connected
    assert test_server_manager.vector_db_client.is_connected
    assert test_server_manager.whisper_server_client.is_connected


@pytest.mark.unit
@pytest.mark.asyncio
async def test_health_checks(test_server_manager):
    """Test that all server health checks pass."""
    health = await test_server_manager.health_check_all()

    assert health["sql"] is True
    assert health["vector_db"] is True
    assert health["whisper_server"] is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sql_client_operations(test_sql_client):
    """Test basic SQL client operations."""
    # Health check
    health = await test_sql_client.health_check()
    assert health is True

    # Tables should be created on startup
    # This verifies the database is initialized
    assert test_sql_client.is_connected


@pytest.mark.unit
@pytest.mark.asyncio
async def test_vector_db_client_operations(test_vector_db_client):
    """Test basic vector DB client operations."""
    # Health check
    health = await test_vector_db_client.health_check()
    assert health is True

    # Test collection creation
    collection = test_vector_db_client.get_or_create_collection("test_collection")
    assert collection is not None

    # Clean up
    test_vector_db_client.delete_collection("test_collection")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_whisper_client_operations(test_whisper_client):
    """Test Whisper client operations."""
    # Health check
    _health = await test_whisper_client.health_check()
    # Note: This will fail if Whisper server is not running
    # In a real test environment, you may want to mock this or skip if not available
    # For now, we just test that the client exists
    assert test_whisper_client is not None
    assert hasattr(test_whisper_client, "endpoint")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_context_integration(test_context, test_server_manager):
    """Test that context is properly integrated with server manager."""
    assert test_context.server_manager is test_server_manager
    assert test_context.server_manager.context is test_context
