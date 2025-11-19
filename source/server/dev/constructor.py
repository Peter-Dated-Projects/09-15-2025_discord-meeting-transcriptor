import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from source.context import Context

from source.server.common import chroma, whisper_server
from source.server.dev.mysql import MySQLServer
from source.server.server import ServerManager

load_dotenv(dotenv_path=".env.local")

# -------------------------------------------------------------- #
# Constructor for Development Server Manager
# -------------------------------------------------------------- #


def load_sql_client() -> MySQLServer:
    """Load and return the SQL client for development."""
    host = os.getenv("SQL_HOST")
    port = int(os.getenv("SQL_PORT", "3306"))
    user = os.getenv("SQL_USER")
    password = os.getenv("SQL_PASSWORD")
    database = os.getenv("SQL_DATABASE")

    if not host or not user or not password or not database:
        raise ValueError("Missing required SQL environment variables.")

    # create MySQL server handler
    sql_handler = MySQLServer(host=host, port=port, user=user, password=password, database=database)
    return sql_handler


def load_vectordb_client():
    """Load and return the VectorDB client for development."""
    host = os.getenv("CHROMADB_HOST", "localhost")
    port = int(os.getenv("CHROMADB_PORT", "8000"))

    # create VectorDB client
    vector_db_client = chroma.construct_vector_db_client(host=host, port=port)
    return vector_db_client


def load_whisper_server_client():
    """Load and return the Whisper server client for development."""
    # Use Flask microservice endpoint instead of direct whisper-server
    endpoint = os.getenv("WHISPER_FLASK_ENDPOINT")

    # Fallback to direct whisper-server if Flask endpoint not configured
    if not endpoint:
        host = os.getenv("WHISPER_HOST", "localhost")
        port = int(os.getenv("WHISPER_PORT", "50021"))
        endpoint = f"http://{host}:{port}"

    # create Whisper server client
    whisper_server_client = whisper_server.construct_whisper_server_client(endpoint=endpoint)
    return whisper_server_client


def construct_server_manager(context: "Context") -> ServerManager:
    """
    Construct and return a ServerManager instance.

    Args:
        context: Context instance to pass to ServerManager

    Returns:
        Configured ServerManager instance
    """
    sql_client = load_sql_client()
    vector_db_client = load_vectordb_client()
    whisper_server_client = load_whisper_server_client()

    # create server manager
    server_manager = ServerManager(
        context=context,
        sql_client=sql_client,
        vector_db_client=vector_db_client,
        whisper_server_client=whisper_server_client,
    )

    return server_manager
