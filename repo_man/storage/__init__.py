"""Storage backends for repo data."""

from repo_man.storage.base import StorageBackend
from repo_man.storage.local import LocalStorageBackend

__all__ = ["StorageBackend", "LocalStorageBackend"]
