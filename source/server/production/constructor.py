import os
from dotenv import dotenv

from source.server.server import ServerManager
from source.server.production.postgresql import PostgreSQLServer


dotenv.load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Constructor for Production Server Manager
# -------------------------------------------------------------- #


def load_sql_client():
    """Load and return the SQL client for production."""
    host = os.getenv("SQL_HOST")
    port = int(os.getenv("SQL_PORT"))
    user = os.getenv("SQL_USER")
    password = os.getenv("SQL_PASSWORD")
    database = os.getenv("SQL_DATABASE")
    if not host or not user or not password or not database:
        raise ValueError("Missing required SQL environment variables.")

    # create PostgreSQL server handler
    sql_handler = PostgreSQLServer(host=host, user=user, password=password, database=database)
    return sql_handler


def construct_server_manager() -> ServerManager:
    """Construct and return a production ServerManager instance."""

    sql_handler = load_sql_client()

    # create server manager
    server_manager = ServerManager(sql_client=sql_handler)

    return server_manager
