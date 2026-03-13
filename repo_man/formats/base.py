"""Abstract format interface for a repository type (APT, RPM)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import PurePath
from typing import Any

from repo_man.storage.base import StorageBackend


class FormatBackend(ABC):
    """Abstract interface for a repo format: cache from upstream, publish, generate metadata, prune."""

    @abstractmethod
    def cache_fetch_metadata(self, upstream_id: str, upstream_config: dict[str, Any]) -> None:
        """Fetch and optionally cache metadata from upstream (e.g. Release, Packages)."""
        ...

    @abstractmethod
    def cache_get_or_fetch_package(
        self,
        upstream_id: str,
        relative_path: str,
        upstream_config: dict[str, Any],
        storage: StorageBackend,
    ) -> bytes | None:
        """Return package bytes from cache or fetch from upstream, store, then return."""
        ...

    @abstractmethod
    def publish_packages(
        self,
        path_prefix: str,
        deb_paths: list[PurePath],
        suite: str,
        component: str,
        arch: str,
        storage: StorageBackend,
    ) -> bool:
        """Ingest .deb files, generate Packages and Release. Return True if changed."""
        ...

    @abstractmethod
    def prune(self, upstream_id: str, storage: StorageBackend, keep_versions_per_package: int) -> int:
        """Remove old package versions beyond keep_versions_per_package. Return number removed."""
        ...
