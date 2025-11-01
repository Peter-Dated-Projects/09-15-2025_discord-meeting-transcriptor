from source.server.server import ServerManager
from source.services.manager import SQLLoggingManagerBase


# -------------------------------------------------------------- #
# SQL Logging Manager Service
# -------------------------------------------------------------- #


class SQLLoggingManagerService(SQLLoggingManagerBase):
    """Service for managing SQL logging."""

    def __init__(self, server: ServerManager):
        super().__init__(server)
