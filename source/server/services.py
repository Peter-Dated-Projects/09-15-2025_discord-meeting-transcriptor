from abc import abstractmethod
from typing import Any

from .server import BaseSQLServerHandler

# -------------------------------------------------------------- #
# Base Service Structures
# -------------------------------------------------------------- #


# Base SQL Database Handler


class SQLDatabase(BaseSQLServerHandler):
    """SQL Database server handler."""

    def __init__(self, name: str, connection_string: str):
        super().__init__(name)
        self.connection_string = connection_string
        self.connection = None

    # ------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------ #

    @abstractmethod
    async def query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
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
    async def insert(self, table: str, data: dict[str, Any]) -> None:
        """
        Insert data into a table.

        Args:
            table: Table name
            data: Data to insert as a dictionary
        """
        pass

    @abstractmethod
    async def update(self, table: str, data: dict[str, Any], conditions: dict[str, Any]) -> None:
        """
        Update data in a table.

        Args:
            table: Table name
            data: Data to update as a dictionary
            conditions: Conditions for the update as a dictionary
        """
        pass
