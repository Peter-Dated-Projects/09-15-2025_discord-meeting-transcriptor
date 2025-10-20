from abc import ABC, abstractmethod
from server import BaseServerHandler

from typing import Any, Dict, List, Optional


# -------------------------------------------------------------- #
# Base Service Structures
# -------------------------------------------------------------- #


class SQLDatabase(BaseServerHandler):
    """SQL Database server handler."""

    def __init__(self, name: str, connection_string: str):
        super().__init__(name)
        self.connection_string = connection_string
        self.connection = None

    # ------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------ #

    @abstractmethod
    async def query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a SQL query.

        Args:
            query: SQL query string
            params: Optional parameters for the query

        Returns:
            List of result rows as dictionaries
        """
        pass

    @abstractmethod
    async def insert(self, table: str, data: Dict[str, Any]) -> None:
        """
        Insert data into a table.

        Args:
            table: Table name
            data: Data to insert as a dictionary
        """
        pass

    @abstractmethod
    async def update(self, table: str, data: Dict[str, Any], conditions: Dict[str, Any]) -> None:
        """
        Update data in a table.

        Args:
            table: Table name
            data: Data to update as a dictionary
            conditions: Conditions for the update as a dictionary
        """
        pass


class VectorDatabase(BaseServerHandler):
    """Vector Database server handler."""

    def __init__(self, name: str, api_key: str):
        super().__init__(name)
        self.api_key = api_key

    # ------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------ #

    @abstractmethod
    async def insert_vector(self, vector: List[float], metadata: Dict[str, Any]) -> str:
        """
        Insert a vector into the database.

        Args:
            vector: Vector data as a list of floats
            metadata: Associated metadata as a dictionary

        Returns:
            ID of the inserted vector
        """
        pass

    @abstractmethod
    async def query_vector(self, vector: List[float], top_k: int) -> List[Dict[str, Any]]:
        """
        Query similar vectors from the database.

        Args:
            vector: Query vector as a list of floats
            top_k: Number of top similar vectors to retrieve

        Returns:
            List of similar vectors and their metadata
        """
        pass

    @abstractmethod
    async def delete_vector(self, vector_id: str) -> None:
        """
        Delete a vector from the database.

        Args:
            vector_id: ID of the vector to delete
        """
        pass

    @abstractmethod
    async def update_vector(self, vector_id: str, new_vector: List[float], metadata: Dict[str, Any]) -> None:
        """
        Update a vector in the database.

        Args:
            vector_id: ID of the vector to update
            new_vector: New vector data as a list of floats
            metadata: Updated metadata as a dictionary
        """
        pass
