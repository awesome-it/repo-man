"""RepoService: core repo logic shared by HTTP handlers.

This module centralises path resolution and cache/backend access so that
`RepoHTTPRequestHandler` in `serve.py` can stay thinner and tests can
exercise behaviour without constructing full HTTP requests.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Tuple

from urllib.parse import unquote

from repo_man.disk import free_disk_until_under_watermark
from repo_man.formats.registry import get_backend
from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class RepoService:
    """Core repo operations: resolve paths, talk to format backends, and handle cache/TTL."""

    def __init__(
        self,
        storage: StorageBackend,
        upstreams: list[dict[str, Any]],
        local_prefixes: list[str] | None,
        metadata_ttl_seconds: int,
        package_hash_store: Any | None,
        disk_high_watermark_bytes: int | None,
        get_disk_usage_fn: Callable[[], int] | None,
        keep_versions_per_package: int,
    ) -> None:
        self.storage = storage
        self.upstreams = upstreams
        self.local_prefixes = local_prefixes or []
        self.metadata_ttl_seconds = metadata_ttl_seconds
        self.package_hash_store = package_hash_store
        self.disk_high_watermark_bytes = disk_high_watermark_bytes
        self.get_disk_usage_fn = get_disk_usage_fn
        self.keep_versions_per_package = keep_versions_per_package

    # ---- Path resolution -------------------------------------------------

    def _path_prefix_to_storage_prefix(self, path_prefix: str) -> str | None:
        """Map request path prefix to storage prefix. Returns cache/name or local/name."""
        path_prefix = path_prefix.rstrip("/") or "/"
        for u in self.upstreams:
            p = (u.get("path_prefix") or "/").rstrip("/") or "/"
            if path_prefix == p or path_prefix.startswith(p + "/"):
                name = u.get("name")
                if name:
                    return f"cache/{name}"
        for lp in self.local_prefixes:
            lp_norm = lp.rstrip("/") or "/"
            if path_prefix == lp_norm or path_prefix.startswith(lp_norm + "/"):
                return (lp.strip("/") or "local").lstrip("/")
        return None

    def resolve(self, raw_path: str | None) -> Tuple[str | None, str]:
        """Resolve an HTTP path to (storage_key or None, path_prefix_for_metrics)."""
        path = unquote(raw_path or "").strip("/")
        if not path:
            return None, "/"
        if path == "metrics":
            return "METRICS", "/metrics"
        parts = path.split("/")
        # path_prefix for metrics is always the first segment
        path_prefix = "/" + (parts[0] if parts else "")
        # Match shortest path_prefix so we get the full suffix for storage key
        for i in range(1, len(parts) + 1):
            prefix = "/" + "/".join(parts[:i])
            storage_prefix = self._path_prefix_to_storage_prefix(prefix)
            if storage_prefix:
                suffix = "/".join(parts[i:]) if i < len(parts) else ""
                key = f"{storage_prefix}/{suffix}" if suffix else storage_prefix
                return key, path_prefix
        return None, path_prefix

    # ---- Cache / backend helpers used by serve.py ------------------------

    def maybe_refresh_metadata_ttl(self, key: str, data: bytes | None) -> bytes | None:
        """Apply metadata TTL: if stale, drop cache entry so backend will refetch."""
        if (
            data is None
            or not key.startswith("cache/")
            or self.metadata_ttl_seconds <= 0
        ):
            return data
        if key.endswith((".deb", ".rpm", ".apk")):
            return data
        fetched_at_bytes = self.storage.get(key + ".fetched_at")
        if fetched_at_bytes is None:
            data = None
        else:
            try:
                fetched_at = float(fetched_at_bytes.decode("utf-8").strip())
                if time.time() - fetched_at > self.metadata_ttl_seconds:
                    data = None
            except (ValueError, UnicodeDecodeError):
                data = None
        # Only delete when key still exists; callers may want to inspect storage.
        if data is None:
            self.storage.delete(key)
            self.storage.delete(key + ".fetched_at")
        return data

    def maybe_prune_old_versions(self) -> None:
        """Invoke format backends to prune old versions per upstream."""
        if self.keep_versions_per_package <= 0:
            return
        total_removed = 0
        for u in self.upstreams:
            name = u.get("name")
            if not name:
                continue
            fmt = u.get("format", "apt")
            try:
                backend = get_backend(fmt)
                removed = backend.prune_upstream(
                    self.storage,
                    name,
                    self.keep_versions_per_package,
                )
                total_removed += removed
            except ValueError:
                continue
        if total_removed:
            logger.info(
                "Auto-pruned %s cached package(s) (keep %s version(s) per package)",
                total_removed,
                self.keep_versions_per_package,
            )

    def maybe_free_disk_over_watermark(self) -> None:
        """Apply disk watermark pruning via repo_man.disk."""
        if self.disk_high_watermark_bytes is None or self.get_disk_usage_fn is None:
            return
        usage = self.get_disk_usage_fn()
        if usage <= self.disk_high_watermark_bytes:
            return
        if not self.upstreams:
            return
        removed = free_disk_until_under_watermark(
            self.storage,
            self.upstreams,
            self.disk_high_watermark_bytes,
            self.get_disk_usage_fn,
            hash_store=self.package_hash_store,
        )
        if removed:
            logger.info("Auto-pruned %s cached package(s) (disk over high watermark)", removed)

