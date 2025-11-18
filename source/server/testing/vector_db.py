"""
In-memory ChromaDB client for testing.

This module provides an in-memory ChromaDB implementation for testing
without requiring a running ChromaDB server.
"""

import logging

from source.server.services import VectorDBDatabase

logger = logging.getLogger(__name__)


class InMemoryChromaDBClient(VectorDBDatabase):
    """In-memory ChromaDB vector database client for testing."""

    def __init__(self, name: str = "test_chromadb"):
        """
        Initialize in-memory ChromaDB client.

        Args:
            name: Name of the client
        """
        super().__init__(name, None)
        self._collections = {}

    async def connect(self) -> None:
        """Establish connection to in-memory ChromaDB."""
        try:
            # Import chromadb here to avoid dependency issues if not installed
            import chromadb

            # Create in-memory client
            self.client = chromadb.Client()
            self._connected = True
            logger.info(f"[{self.name}] Connected to in-memory ChromaDB")
        except Exception as e:
            logger.error(f"[{self.name}] Failed to connect: {e}")
            raise

    async def disconnect(self) -> None:
        """Close connection to in-memory ChromaDB."""
        # In-memory client doesn't require explicit disconnection
        self.client = None
        self._collections = {}
        self._connected = False
        logger.info(f"[{self.name}] Disconnected from in-memory ChromaDB")

    async def health_check(self) -> bool:
        """Check if ChromaDB is healthy."""
        try:
            if self.client:
                # Try to get heartbeat
                self.client.heartbeat()
                return True
            return False
        except Exception as e:
            logger.error(f"[{self.name}] Health check failed: {e}")
            return False

    async def create_tables(self) -> None:
        """Create collections in ChromaDB (no-op for vector DB)."""
        # Vector databases don't have traditional tables
        # Collections are created on-demand
        pass

    def get_or_create_collection(self, name: str):
        """
        Get or create a collection.

        Args:
            name: Collection name

        Returns:
            Collection instance
        """
        if not self.client:
            raise RuntimeError("Not connected to ChromaDB")

        if name not in self._collections:
            self._collections[name] = self.client.get_or_create_collection(name=name)

        return self._collections[name]

    def delete_collection(self, name: str) -> None:
        """
        Delete a collection.

        Args:
            name: Collection name
        """
        if not self.client:
            raise RuntimeError("Not connected to ChromaDB")

        if name in self._collections:
            del self._collections[name]

        self.client.delete_collection(name=name)

    def reset(self) -> None:
        """Reset all collections (useful for test cleanup)."""
        if self.client:
            self._collections = {}
            self.client.reset()
