"""Alpine format backend for the format registry."""

from __future__ import annotations

from typing import Any

from repo_man.storage.base import StorageBackend

from repo_man.formats.alpine import cache as alpine_cache


class AlpineBackend:
    """Backend used by registry for format='alpine'."""

    def get_or_fetch(
        self,
        upstream_id: str,
        path_suffix: str,
        upstream_config: dict[str, Any],
        storage: StorageBackend,
        package_hash_store: Any = None,
    ) -> tuple[bytes | None, bool]:
        return alpine_cache.get_or_fetch(
            upstream_id,
            path_suffix,
            upstream_config,
            storage,
            package_hash_store=package_hash_store,
        )

    def prune_upstream(
        self,
        storage: StorageBackend,
        upstream_id: str,
        keep_versions_per_package: int,
    ) -> int:
        return alpine_cache.prune_upstream(storage, upstream_id, keep_versions_per_package)


backend = AlpineBackend()
