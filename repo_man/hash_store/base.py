"""Abstract package hash store: path -> hash and last_served for cached packages."""

from __future__ import annotations

from abc import ABC, abstractmethod


class PackageHashStore(ABC):
    """Store (upstream_id, path) -> hash and optional last_served timestamp for cached packages."""

    @abstractmethod
    def get(self, upstream_id: str, path: str) -> str | None:
        """Return stored hash for path, or None if not found."""
        ...

    @abstractmethod
    def set(self, upstream_id: str, path: str, hash_value: str) -> None:
        """Store hash for path."""
        ...

    @abstractmethod
    def delete(self, upstream_id: str, path: str) -> None:
        """Remove stored hash and last_served for path."""
        ...

    @abstractmethod
    def list_paths(self, upstream_id: str) -> list[str]:
        """Return all paths with stored hashes for this upstream."""
        ...

    @abstractmethod
    def set_last_served(self, upstream_id: str, path: str, timestamp: float) -> None:
        """Record when a package was last served to a client."""
        ...

    @abstractmethod
    def get_last_served(self, upstream_id: str, path: str) -> float | None:
        """Return last served timestamp for path, or None if never recorded."""
        ...
