# Base Vectordb database handler

import logging
from typing import Any

from source.server.services import VectorDBDatabase
from source.server.vector_db_collections import DEFAULT_VECTORDB_COLLECTIONS

logger = logging.getLogger(__name__)


class ChromaDBClient(VectorDBDatabase):
    """ChromaDB vector database client."""

    def __init__(
        self, name: str = "chromadb", host: str = "localhost", port: int = 8000, client: Any = None
    ):
        """
        Initialize ChromaDB client.

        Args:
            name: Name of the client
            host: ChromaDB server host
            port: ChromaDB server port
            client: Optional pre-configured client
        """
        super().__init__(name, client)
        self.host = host
        self.port = port

    async def connect(self) -> None:
        """Establish connection to ChromaDB server."""
        try:
            # Import chromadb here to avoid dependency issues if not installed
            import chromadb
            from chromadb.config import Settings

            self.client = chromadb.HttpClient(
                host=self.host,
                port=self.port,
                settings=Settings(
                    chroma_client_auth_provider=None,
                    chroma_client_auth_credentials=None,
                ),
            )
            self._connected = True
            logger.info(f"Connected to ChromaDB at {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to ChromaDB: {e}")
            raise

    async def disconnect(self) -> None:
        """Close connection to ChromaDB server."""
        # ChromaDB HTTP client doesn't require explicit disconnection
        self._connected = False
        logger.info("Disconnected from ChromaDB")

    async def health_check(self) -> bool:
        """Check if ChromaDB server is healthy."""
        try:
            if self.client:
                # Try to get heartbeat
                self.client.heartbeat()
                return True
            return False
        except Exception as e:
            logger.error(f"ChromaDB health check failed: {e}")
            return False

    async def create_default_collections(self) -> None:
        """Create default collections that must exist on startup."""
        if not self.client:
            logger.error("Cannot create collections: ChromaDB client not connected")
            raise RuntimeError("ChromaDB client not connected")

        logger.info(f"Creating default collections: {DEFAULT_VECTORDB_COLLECTIONS}")
        for collection_name in DEFAULT_VECTORDB_COLLECTIONS:
            if not await self.collection_exists(collection_name):
                await self.create_collection(collection_name)
                logger.info(f"Created collection: {collection_name}")
            else:
                logger.info(f"Collection already exists: {collection_name}")

    async def collection_exists(self, name: str) -> bool:
        """
        Check if a collection exists.

        Args:
            name: Collection name

        Returns:
            True if collection exists, False otherwise
        """
        if not self.client:
            raise RuntimeError("ChromaDB client not connected")

        try:
            self.client.get_collection(name=name)
            return True
        except Exception:
            return False

    async def create_collection(self, name: str) -> None:
        """
        Create a collection.

        Args:
            name: Collection name
        """
        if not self.client:
            raise RuntimeError("ChromaDB client not connected")

        try:
            self.client.create_collection(name=name)
            logger.info(f"Successfully created collection: {name}")
        except Exception as e:
            logger.error(f"Failed to create collection {name}: {e}")
            raise

    async def create_tables(self) -> None:
        """Create collections in ChromaDB (no-op for vector DB)."""
        # Vector databases don't have traditional tables
        # Collections are created on-demand
        pass


def construct_vector_db_client(host: str = "localhost", port: int = 8000) -> ChromaDBClient:
    """
    Construct and return a VectorDB client.

    Args:
        host: ChromaDB server host
        port: ChromaDB server port

    Returns:
        Configured ChromaDBClient instance
    """
    return ChromaDBClient(name="chromadb", host=host, port=port)
