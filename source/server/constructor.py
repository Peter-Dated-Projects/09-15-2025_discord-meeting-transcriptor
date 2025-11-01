from source.constructor import ServerManagerType
from source.server.server import ServerManager

# -------------------------------------------------------------- #
# Constructor for Dynamic Creation of Server Manager
# -------------------------------------------------------------- #


def construct_server_manager(client_type: ServerManagerType) -> "ServerManager":
    """Construct and return a ServerManager instance with given SQL handler and file storage path."""

    if client_type == ServerManagerType.DEVELOPMENT:
        from source.server.dev.constructor import construct_server_manager

        return construct_server_manager()
    elif client_type == ServerManagerType.PRODUCTION:
        from source.server.constructor import construct_server_manager

        return construct_server_manager()

    raise ValueError(f"Unsupported ServerManagerType: {client_type}")
