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
    # Utils
    # ------------------------------------------------------ #

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
