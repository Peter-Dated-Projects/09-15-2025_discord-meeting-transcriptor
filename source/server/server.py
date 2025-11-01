"""
Server service handlers for external services.

This module provides base classes and managers for handling connections
and operations with external services.
"""

from abc import ABC, abstractmethod

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

    async def on_startup(self) -> None:
        """Actions to perform on server startup."""
        pass


# -------------------------------------------------------------- #
# Server Manager
# -------------------------------------------------------------- #


class ServerManager:
    """Manager for handling multiple server instances."""

    def __init__(self, sql_client: BaseSQLServerHandler):
        self._initialized = False
        self._sql_client = sql_client
        self._servers = {"sql": sql_client}

    # ------------------------------------------------------ #
    # Server Management
    # ------------------------------------------------------ #

    async def connect_all(self) -> None:
        """Connect all registered servers."""
        print(f"[ServerManager] Connecting {len(self._servers)} server(s)...")
        for name, server in self._servers.items():
            try:
                await server.connect()
                print(f"[ServerManager] Connected {name}")
            except Exception as e:
                print(f"[ServerManager] Failed to connect {name}: {e}")
                raise
        self._initialized = True

    async def disconnect_all(self) -> None:
        """Disconnect all registered servers."""
        print(f"[ServerManager] Disconnecting {len(self._servers)} server(s)...")
        for name, server in self._servers.items():
            try:
                await server.disconnect()
                print(f"[ServerManager] Disconnected {name}")
            except Exception as e:
                print(f"[ServerManager] Failed to disconnect {name}: {e}")

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
