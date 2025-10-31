"""
Server service handlers for external services.

This module provides base classes and managers for handling connections
and operations with external services.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List


# -------------------------------------------------------------- #
# Base Server Handlers
# -------------------------------------------------------------- #


# Base SQL Server Handlers
class BaseSQLServerHandler(ABC):
    """Abstract base class for SQL server handlers."""

    def __init__(self, name: str):
        self.name = name
        self._connected = False

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

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to the server."""
        return self._connected


# -------------------------------------------------------------- #
# Server Manager
# -------------------------------------------------------------- #


class ServerManager:
    """Manager for handling multiple server instances."""

    def __init__(self, sql_client: BaseSQLServerHandler, vectordb_client=None):
        self._sql_client = sql_client
        # self._vectordb_client = vectordb_client

    # ------------------------------------------------------ #
    # Server Management
    # ------------------------------------------------------ #

    async def connect_all(self) -> None:
        """Connect all registered servers."""
        print(f"[ServerManager] Connecting {len(self._servers)} server(s)...")
        for name, server in self._servers.items():
            try:
                await server.connect()
            except Exception as e:
                print(f"[ServerManager] Failed to connect {name}: {e}")

    async def disconnect_all(self) -> None:
        """Disconnect all registered servers."""
        print(f"[ServerManager] Disconnecting {len(self._servers)} server(s)...")
        for name, server in self._servers.items():
            try:
                await server.disconnect()
            except Exception as e:
                print(f"[ServerManager] Failed to disconnect {name}: {e}")

    async def health_check_all(self) -> Dict[str, bool]:
        """
        Check health of all registered servers.

        Returns:
            Dictionary mapping server names to health status
        """
        results = {}
        for name, server in self._servers.items():
            results[name] = await server.health_check()
        return results

    def list_servers(self) -> List[str]:
        """Get list of all registered server names."""
        return list(self._servers.keys())
