"""Abstract storage backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import PurePath
from typing import BinaryIO, Iterator


class StorageBackend(ABC):
    """Abstract interface for storing and retrieving repo artifacts by path."""

    @abstractmethod
    def get(self, path: str | PurePath) -> bytes | None:
        """Read object at path; return None if not found."""
        ...

    @abstractmethod
    def put(self, path: str | PurePath, data: bytes | BinaryIO) -> None:
        """Write data at path. Overwrites if exists."""
        ...

    @abstractmethod
    def list_prefix(self, prefix: str | PurePath) -> Iterator[str]:
        """Yield keys under prefix (e.g. 'upstream/ubuntu/' -> 'upstream/ubuntu/Release')."""
        ...

    @abstractmethod
    def delete(self, path: str | PurePath) -> bool:
        """Remove object at path. Return True if removed, False if not found."""
        ...

    @abstractmethod
    def exists(self, path: str | PurePath) -> bool:
        """Return True if path exists."""
        ...
