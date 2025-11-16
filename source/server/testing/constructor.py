"""
Constructor for Testing Server Manager.

This module provides functions to construct a ServerManager instance
with in-memory database implementations for testing purposes.
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context

from source.server.server import ServerManager
from source.server.common import whisper_server
from source.server.testing.mysql import InMemoryMySQLServer
from source.server.testing.vector_db import InMemoryChromaDBClient

# -------------------------------------------------------------- #
# Constructor for Testing Server Manager
# -------------------------------------------------------------- #


def load_sql_client() -> InMemoryMySQLServer:
    """Load and return the in-memory SQL client for testing."""
    sql_handler = InMemoryMySQLServer(name="test_mysql")
    return sql_handler


def load_vectordb_client() -> InMemoryChromaDBClient:
    """Load and return the in-memory VectorDB client for testing."""
    vector_db_client = InMemoryChromaDBClient(name="test_chromadb")
    return vector_db_client


def load_whisper_server_client():
    """Load and return the Whisper server client for testing."""
    # Use Flask microservice endpoint instead of direct whisper-server
    endpoint = os.getenv("WHISPER_FLASK_ENDPOINT")

    # Fallback to direct whisper-server if Flask endpoint not configured
    if not endpoint:
        host = os.getenv("WHISPER_HOST", "localhost")
        port = int(os.getenv("WHISPER_PORT", "50021"))
        endpoint = f"http://{host}:{port}"

    # create Whisper server client using common implementation
    whisper_server_client = whisper_server.construct_whisper_server_client(endpoint=endpoint)
    return whisper_server_client


def construct_server_manager(context: "Context") -> ServerManager:
    """
    Construct and return a ServerManager instance for testing.

    This creates a ServerManager with all in-memory/mock implementations:
    - In-memory SQLite database (mimics MySQL)
    - In-memory ChromaDB
    - Mock Whisper server

    Args:
        context: Context instance to pass to ServerManager

    Returns:
        Configured ServerManager instance with test implementations
    """
    sql_client = load_sql_client()
    vector_db_client = load_vectordb_client()
    whisper_server_client = load_whisper_server_client()

    # create server manager
    server_manager = ServerManager(
        context=context,
        sql_client=sql_client,
        vector_db_client=vector_db_client,
        whisper_server_client=whisper_server_client,
    )

    return server_manager
