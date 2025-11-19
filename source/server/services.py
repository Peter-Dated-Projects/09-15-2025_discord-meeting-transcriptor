from abc import ABC, abstractmethod
from typing import Any

# -------------------------------------------------------------- #
# Base Server Handler
# -------------------------------------------------------------- #


class BaseServerHandler(ABC):
    """Abstract base class for all server handlers."""

    def __init__(self, name: str):
        self.name = name
        self._connected = False

    # -------------------------------------------------------------- #
    # Handler Methods
    # -------------------------------------------------------------- #

    async def on_startup(self) -> None:
        """Actions to perform on server startup."""
        pass

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

    @property
    def is_connected(self) -> bool:
        """Check if currently connected to the server."""
        return self._connected


# -------------------------------------------------------------- #
# Base Service Structures
# -------------------------------------------------------------- #


# Base SQL Database Handler


class SQLDatabase(BaseServerHandler):
    """SQL Database server handler."""

    def __init__(self, name: str, connection_string: str):
        super().__init__(name)
        self.connection_string = connection_string
        self.connection = None

    # -------------------------------------------------------------- #
    # Handler Methods
    # -------------------------------------------------------------- #

    async def on_startup(self) -> None:
        await self.create_tables()

    # ------------------------------------------------------ #
    # Utils
    # ------------------------------------------------------ #

    @abstractmethod
    async def create_tables(self) -> None:
        """Create database tables from models."""
        pass

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
    async def execute(self, stmt) -> list[dict[str, Any]]:
        """
        Execute a SQLAlchemy statement and return results.

        Args:
            stmt: SQLAlchemy statement object (select, insert, update, delete)

        Returns:
            List of result rows as dictionaries (empty list for non-SELECT queries)
        """
        pass


# VectorDB Database Handler


class VectorDBDatabase(BaseServerHandler):
    """VectorDB Database server handler."""

    def __init__(self, name: str, client: Any):
        super().__init__(name)
        self.client = client

    # -------------------------------------------------------------- #
    # Handler Methods
    # -------------------------------------------------------------- #

    async def on_startup(self) -> None:
        """Actions to perform on server startup - create default collections."""
        await self.create_default_collections()

    # ------------------------------------------------------ #
    # Utils
    # ------------------------------------------------------ #

    @abstractmethod
    async def create_default_collections(self) -> None:
        """Create default collections that must exist on startup."""
        pass

    @abstractmethod
    async def collection_exists(self, name: str) -> bool:
        """
        Check if a collection exists.

        Args:
            name: Collection name

        Returns:
            True if collection exists, False otherwise
        """
        pass

    @abstractmethod
    async def create_collection(self, name: str) -> None:
        """
        Create a collection.

        Args:
            name: Collection name
        """
        pass


# Whisper Server Handler
class WhisperServerHandler(BaseServerHandler):
    """Whisper Server handler."""

    def __init__(self, name: str, endpoint: str):
        super().__init__(name)
        self.endpoint = endpoint

    # -------------------------------------------------------------- #
    # Methods
    # -------------------------------------------------------------- #

    @abstractmethod
    async def select_load_model(self, model_path: str) -> None:
        """
        Load a Whisper model on the server.

        Args:
            model_name: Name of the model to load
        """
        pass

    @abstractmethod
    async def inference(self, audio_path: str) -> str:
        """
        Perform transcription on the given audio file.

        Args:
            audio_path: Path to the audio file

        Returns:
            Transcribed text
        """
        pass
