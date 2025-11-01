import os

from dotenv import load_dotenv

from source.server.production.postgresql import PostgreSQLServer
from source.server.server import ServerManager
from source.constructor import ServerManagerType

load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Constructor for Production Server Manager
# -------------------------------------------------------------- #


def load_sql_client() -> PostgreSQLServer:
    """Load and return the SQL client for production."""
    host = os.getenv("SQL_HOST")
    port = int(os.getenv("SQL_PORT", "5432"))
    user = os.getenv("SQL_USER")
    password = os.getenv("SQL_PASSWORD")
    database = os.getenv("SQL_DATABASE")

    if not host or not user or not password or not database:
        raise ValueError("Missing required SQL environment variables.")

    # create PostgreSQL server handler
    sql_handler = PostgreSQLServer(
        host=host, port=port, user=user, password=password, database=database
    )
    return sql_handler


def construct_server_manager(
    manager_type: ServerManagerType = ServerManagerType.PRODUCTION, storage_path: str = "./data"
) -> ServerManager:
    """
    Construct and return a ServerManager instance for production.

    Args:
        manager_type: Type of server manager (PRODUCTION)
        storage_path: Path for storing data (optional for SQL-based storage)

    Returns:
        Configured ServerManager instance
    """
    sql_handler = load_sql_client()

    # create server manager
    server_manager = ServerManager(sql_client=sql_handler)

    return server_manager
