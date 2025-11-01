import os


# -------------------------------------------------------------- #
# File Manager Service
# -------------------------------------------------------------- #


class FileManagerService:
    """Service for managing file storage and retrieval."""

    def __init__(self, storage_path: str):
        self.storage_path = storage_path

    def save_file(self, filename: str, data: bytes) -> None:
        """Save a file to the storage path."""
        with open(os.path.join(self.storage_path, filename), "wb") as f:
            f.write(data)

    def read_file(self, filename: str) -> bytes:
        """Read a file from the storage path."""
        with open(os.path.join(self.storage_path, filename), "rb") as f:
            return f.read()
