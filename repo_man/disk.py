"""Disk usage and format-agnostic cache eviction for disk watermark."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

PACKAGE_EXTENSIONS = (".deb", ".rpm", ".apk")


def get_repo_disk_usage_bytes(repo_root: Path | str) -> int:
    """Return total size in bytes of all files under repo_root. Published (e.g. local/) is included."""
    root = Path(repo_root)
    if not root.exists() or not root.is_dir():
        return 0
    total = 0
    try:
        for f in root.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError as e:
                    logger.warning("Disk usage: could not stat file=%s error=%s", f, e)
    except OSError as e:
        logger.warning("Disk usage failed: root=%s error=%s", root, e)
    return total


def list_cached_package_entries(
    storage: Any,
    upstream_ids: list[str],
    hash_store: Any,
) -> list[tuple[str, str, str, float]]:
    """List cached package paths (any format: .deb, .rpm, .apk) by last_served, oldest first."""
    entries: list[tuple[str, str, str, float]] = []
    for uid in upstream_ids:
        prefix = f"cache/{uid}"
        for storage_path in storage.list_prefix(prefix):
            if not any(storage_path.endswith(ext) for ext in PACKAGE_EXTENSIONS):
                continue
            parts = storage_path.split("/", 2)
            if len(parts) < 3:
                continue
            path = parts[2]
            ts = hash_store.get_last_served(uid, path) if hasattr(hash_store, "get_last_served") else 0.0
            if ts is None:
                ts = 0.0
            entries.append((storage_path, uid, path, float(ts)))
    entries.sort(key=lambda x: x[3])
    return entries


def free_disk_until_under_watermark(
    storage: Any,
    upstreams: list[dict[str, Any]],
    high_watermark_bytes: int,
    get_usage_fn: Callable[[], int],
    hash_store: Any = None,
) -> int:
    """
    When repo usage is above high_watermark_bytes, free cache (never published).
    If hash_store is set: evict by oldest last_served (format-agnostic).
    Else: call each format's prune_upstream(storage, name, 1) then 0 until under.
    """
    from repo_man.formats.registry import get_backend

    upstream_ids = [u["name"] for u in upstreams if u.get("name")]
    if not upstream_ids:
        return 0
    if hash_store is not None:
        total_removed = 0
        while get_usage_fn() > high_watermark_bytes:
            entries = list_cached_package_entries(storage, upstream_ids, hash_store)
            if not entries:
                break
            storage_path, upstream_id, path = entries[0][0], entries[0][1], entries[0][2]
            if storage.delete(storage_path):
                hash_store.delete(upstream_id, path)
                total_removed += 1
                logger.info(
                    "Evicted package (oldest last_served, over watermark): upstream=%s path=%s",
                    upstream_id,
                    path,
                )
        return total_removed
    total_removed = 0
    while get_usage_fn() > high_watermark_bytes:
        round_removed = 0
        for u in upstreams:
            name = u.get("name")
            if not name:
                continue
            fmt = u.get("format", "apt")
            try:
                backend = get_backend(fmt)
                round_removed += backend.prune_upstream(storage, name, keep_versions_per_package=1)
            except ValueError:
                pass
        if round_removed == 0:
            for u in upstreams:
                name = u.get("name")
                if not name:
                    continue
                fmt = u.get("format", "apt")
                try:
                    backend = get_backend(fmt)
                    round_removed += backend.prune_upstream(storage, name, keep_versions_per_package=0)
                except ValueError:
                    pass
            if round_removed == 0:
                break
        total_removed += round_removed
    return total_removed
