"""Alpine pull-through cache: get_or_fetch metadata/packages, prune by version."""

from __future__ import annotations

import logging
import time
from functools import cmp_to_key
from typing import Any

import httpx

from repo_man.formats.alpine.version import compare_versions
from repo_man.metrics import (
    cache_upstream_fetch_errors_total,
    packages_pulled_from_upstream_total,
    upstream_last_access_timestamp_seconds,
)
from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)

# APKINDEX.tar.gz or APKINDEX.xml (v3) at repo root; packages at e.g. main/x86_64/*.apk
ALPINE_METADATA_NAMES = ("APKINDEX.tar.gz", "APKINDEX.xml")


def _storage_prefix(upstream_id: str) -> str:
    return f"cache/{upstream_id}"


def _is_metadata_path(path_suffix: str) -> bool:
    """True if path is APKINDEX or similar metadata."""
    base = path_suffix.split("/")[-1] if "/" in path_suffix else path_suffix
    return base.startswith("APKINDEX") or base == "APKINDEX.tar.gz" or base == "APKINDEX.xml"


def get_or_fetch(
    upstream_id: str,
    path_suffix: str,
    upstream_config: dict[str, Any],
    storage: StorageBackend,
    package_hash_store: Any = None,
) -> tuple[bytes | None, bool]:
    """
    Return bytes from cache or fetch from upstream. Metadata (APKINDEX*) or package (*.apk).
    Returns (data, from_upstream).
    """
    prefix = _storage_prefix(upstream_id)
    key = f"{prefix}/{path_suffix}" if path_suffix else prefix
    existing = storage.get(key)
    if existing is not None:
        return (existing, False)
    base_url = (upstream_config.get("url") or upstream_config.get("base_url", "")).rstrip("/")
    if not base_url:
        return (None, False)
    url = f"{base_url}/{path_suffix.lstrip('/')}"

    if _is_metadata_path(path_suffix):
        try:
            with httpx.Client(follow_redirects=True, timeout=60.0) as client:
                r = client.get(url)
                if r.status_code != 200:
                    cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
                    return (None, False)
                raw = r.content
        except Exception as e:
            cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
            logger.warning("Alpine metadata fetch failed: upstream=%s path=%s error=%s", upstream_id, path_suffix, e)
            return (None, False)
        storage.put(key, raw)
        storage.put(key + ".fetched_at", str(time.time()).encode("utf-8"))
        upstream_last_access_timestamp_seconds.labels(upstream=upstream_id).set(time.time())
        return (raw, True)

    # Package path (*.apk)
    if not path_suffix.endswith(".apk"):
        return (None, False)
    try:
        with httpx.Client(follow_redirects=True, timeout=120.0) as client:
            r = client.get(url)
            if r.status_code != 200:
                cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
                return (None, False)
            storage.put(key, r.content)
            packages_pulled_from_upstream_total.labels(upstream=upstream_id).inc()
            upstream_last_access_timestamp_seconds.labels(upstream=upstream_id).set(time.time())
            logger.info("Saved Alpine package: upstream=%s path=%s", upstream_id, path_suffix)
            return (r.content, True)
    except Exception as e:
        cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
        logger.warning("Alpine package fetch failed: upstream=%s path=%s error=%s", upstream_id, path_suffix, e)
        return (None, False)


def _parse_apk_filename(filename: str) -> tuple[str, str] | None:
    """Parse .apk filename to (name, version). Alpine: name-version.apk or name-version-rN.apk."""
    if not filename.endswith(".apk"):
        return None
    base = filename[:-4]
    if "-" not in base:
        return None
    # Last segment is version (may contain -rN)
    name, version = base.rsplit("-", 1)
    return name, version


def list_cached_packages_by_name(
    storage: StorageBackend,
    upstream_id: str,
) -> dict[str, list[tuple[str, str]]]:
    """List cached .apk paths under cache/upstream_id, grouped by package name. Returns name -> [(version, path)]."""
    prefix = _storage_prefix(upstream_id)
    by_name: dict[str, list[tuple[str, str]]] = {}
    for path in storage.list_prefix(prefix):
        if not path.endswith(".apk"):
            continue
        parts = path.split("/")
        filename = parts[-1] if parts else ""
        parsed = _parse_apk_filename(filename)
        if parsed is None:
            continue
        name, version = parsed
        by_name.setdefault(name, []).append((version, path))
    return by_name


def prune_upstream(
    storage: StorageBackend,
    upstream_id: str,
    keep_versions_per_package: int,
) -> int:
    """Keep latest keep_versions_per_package versions per package; delete the rest. Returns number removed."""
    by_name = list_cached_packages_by_name(storage, upstream_id)
    removed = 0
    for name, version_paths in by_name.items():
        if len(version_paths) <= keep_versions_per_package:
            continue
        sorted_paths = sorted(
            version_paths,
            key=cmp_to_key(lambda a, b: -compare_versions(a[0], b[0])),
        )
        for _ver, path in sorted_paths[keep_versions_per_package:]:
            if storage.delete(path):
                logger.info("Pruned Alpine package: upstream=%s path=%s", upstream_id, path)
                removed += 1
    return removed
