import os

from source.server.server import ServerManager
from source.services.manager import Manager

# -------------------------------------------------------------- #
# File Manager Service
# -------------------------------------------------------------- #


class FileManagerService(Manager):
    """Service for managing file storage and retrieval."""

    def __init__(self, server: ServerManager, storage_path: str):
        super().__init__(server)

        self.storage_path = storage_path

    # -------------------------------------------------------------- #
    # Manager Methods
    # -------------------------------------------------------------- #

    def on_start(self):
        # check if folder exists
        if not os.path.exists(self.storage_path):
            os.makedirs(self.storage_path)

        return True

    def on_close(self):
        return True

    # -------------------------------------------------------------- #
    # File Management Methods
    # -------------------------------------------------------------- #

    def save_file(self, filename: str, data: bytes) -> None:
        """Save a file to the storage path."""
        if os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileExistsError(f"File {filename} already exists.")
        with open(os.path.join(self.storage_path, filename), "wb") as f:
            f.write(data)

    def read_file(self, filename: str) -> bytes:
        """Read a file from the storage path."""
        if not os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileNotFoundError(f"File {filename} does not exist.")
        with open(os.path.join(self.storage_path, filename), "rb") as f:
            return f.read()

    def delete_file(self, filename: str) -> None:
        """Delete a file from the storage path."""
        if not os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileNotFoundError(f"File {filename} does not exist.")
        os.remove(os.path.join(self.storage_path, filename))

    def update_file(self, filename: str, data: bytes) -> None:
        """Update a file in the storage path."""
        if not os.path.exists(os.path.join(self.storage_path, filename)):
            raise FileNotFoundError(f"File {filename} does not exist.")
        with open(os.path.join(self.storage_path, filename), "wb") as f:
            f.write(data)

    def get_folder_contents(self) -> list[str]:
        """Get a list of files in the storage path."""
        return os.listdir(self.storage_path)

    def file_exists(self, filename: str) -> bool:
        """Check if a file exists in the storage path."""
        return os.path.exists(os.path.join(self.storage_path, filename))
