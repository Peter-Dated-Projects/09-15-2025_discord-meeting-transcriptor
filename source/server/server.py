"""
Server service handlers for external services.

This module provides base classes and managers for handling connections
and operations with external services.
"""

import logging
from typing import TYPE_CHECKING

from source.server.services import SQLDatabase, VectorDBDatabase, WhisperServerHandler

if TYPE_CHECKING:
    from source.context import Context

logger = logging.getLogger(__name__)

# -------------------------------------------------------------- #
# Server Manager
# -------------------------------------------------------------- #


class ServerManager:
    """Manager for handling multiple server instances."""

    def __init__(
        self,
        context: "Context",
        sql_client: SQLDatabase,
        vector_db_client: VectorDBDatabase,
        whisper_server_client: WhisperServerHandler,
    ):
        self.context = context
        self._initialized = False
        self._sql_client = sql_client
        self._vector_db_client = vector_db_client
        self._whisper_server_client = whisper_server_client

        self._servers = {
            "sql": sql_client,
            "vector_db": vector_db_client,
            "whisper_server": whisper_server_client,
        }

    # ------------------------------------------------------ #
    # Server Management
    # ------------------------------------------------------ #

    async def connect_all(self) -> None:
        """Connect to all servers."""
        logger.info("=" * 60)
        logger.info("[ServerManager] Connecting all servers...")

        for server in self._servers.values():
            logger.info(f"[ServerManager] Connecting to '{server.name}' server...")
            await server.connect()
            logger.info(f"[ServerManager] Executing startup actions for '{server.name}' server...")
            await server.on_startup()
            logger.info(f"[ServerManager] '{server.name}' server is ready.")

        self._initialized = True
        logger.info("[ServerManager] All servers connected successfully.")
        logger.info("=" * 60)

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        logger.info("=" * 60)
        logger.info("[ServerManager] Disconnecting all servers...")

        for server in self._servers.values():
            logger.info(f"[ServerManager] Executing close actions for '{server.name}' server...")
            await server.on_close()
            logger.info(f"[ServerManager] Disconnecting from '{server.name}' server...")
            await server.disconnect()
            logger.info(f"[ServerManager] '{server.name}' server disconnected.")

        logger.info("[ServerManager] All servers disconnected successfully.")
        logger.info("=" * 60)

    async def health_check_all(self) -> dict[str, bool]:
        """
        Check health of all registered servers.

        Returns:
            Dictionary mapping server names to health status
        """
        results = {}
        for name, server in self._servers.items():
            results[name] = await server.health_check()
        return results

    def list_servers(self) -> list[str]:
        """Get list of all registered server names."""
        return list(self._servers.keys())

    # ------------------------------------------------------ #
    # Properties
    # ------------------------------------------------------ #

    @property
    def sql_client(self) -> SQLDatabase:
        """Get the SQL client."""
        return self._sql_client

    @property
    def vector_db_client(self) -> VectorDBDatabase:
        """Get the VectorDB client."""
        return self._vector_db_client

    @property
    def whisper_server_client(self) -> WhisperServerHandler:
        """Get the Whisper server client."""
        return self._whisper_server_client

    @property
    def is_initialized(self) -> bool:
        """Check if the server manager is initialized."""
        return self._initialized
