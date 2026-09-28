"""Abstract storage backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from pathlib import PurePath
from typing import BinaryIO, Iterator, Protocol


class PartialWriter(Protocol):
    """Writable handle for an in-progress cache object (``.partial`` file)."""

    def write(self, data: bytes) -> None:
        ...

    def flush(self) -> None:
        ...

    def tell(self) -> int:
        ...


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

    def open_read(self, path: str | PurePath) -> BinaryIO | None:
        """Open final object for streaming read; None if missing. Default: buffer via get()."""
        data = self.get(path)
        if data is None:
            return None
        from io import BytesIO

        return BytesIO(data)

    def open_partial_writer(self, path: str | PurePath) -> AbstractContextManager[PartialWriter]:
        """
        Write to ``{path}.partial``; on clean exit rename to ``path``; on error delete partial.
        Backends that do not support streaming should override or raise.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support partial writers")

    def read_partial(self, path: str | PurePath, size: int) -> bytes:
        """Read the first ``size`` bytes of an in-progress partial file (for late-joiner replay)."""
        raise NotImplementedError(f"{type(self).__name__} does not support partial reads")

    def partial_exists(self, path: str | PurePath) -> bool:
        """Return True if a ``.partial`` sibling exists for path."""
        return False
