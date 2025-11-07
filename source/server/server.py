"""
Server service handlers for external services.

This module provides base classes and managers for handling connections
and operations with external services.
"""

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.context import Context

logger = logging.getLogger(__name__)

# -------------------------------------------------------------- #
# Base Server Handlers
# -------------------------------------------------------------- #


# Base SQL Server Handlers
class BaseSQLServerHandler(ABC):
    """Abstract base class for SQL server handlers."""

    def __init__(self, name: str):
        self.name = name
        self._connected = False

    # -------------------------------------------------------------- #
    # Handler Methods
    # -------------------------------------------------------------- #

    async def on_startup(self) -> None:
        """Actions to perform on server startup."""
        await self.create_tables()

    async def on_close(self) -> None:
        """Actions to perform on server close."""
        pass

    # -------------------------------------------------------------- #
    # Abstract Methods
    # -------------------------------------------------------------- #

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the server."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the server."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the server is healthy and responding."""
        pass

    @abstractmethod
    async def create_tables(self) -> None:
        """Create database tables from models."""
        pass

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to the server."""
        return self._connected

    # -------------------------------------------------------------- #
    # Utility Methods
    # -------------------------------------------------------------- #

    @abstractmethod
    def compile_query_object(self, stmt) -> str:
        """
        Compile a SQLAlchemy statement object into a SQL query string.

        Args:
            stmt: SQLAlchemy statement object

        Returns:
            Compiled SQL query string
        """
        pass

    @abstractmethod
    async def execute(self, stmt) -> list[dict]:
        """
        Execute a SQLAlchemy statement and return results.

        Args:
            stmt: SQLAlchemy statement object (select, insert, update, delete)

        Returns:
            List of result rows as dictionaries (empty list for non-SELECT queries)
        """
        pass


# -------------------------------------------------------------- #
# Server Manager
# -------------------------------------------------------------- #


class ServerManager:
    """Manager for handling multiple server instances."""

    def __init__(self, context: "Context", sql_client: BaseSQLServerHandler):
        self.context = context
        self._initialized = False
        self._sql_client = sql_client
        self._servers = {"sql": sql_client}

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

    @property
    def sql_client(self) -> BaseSQLServerHandler:
        """Get the SQL client."""
        return self._sql_client

    @property
    def is_initialized(self) -> bool:
        """Check if the server manager is initialized."""
        return self._initialized
