"""RPM pull-through cache: get_or_fetch metadata/packages, prune by version."""

from __future__ import annotations

import logging
import time
from functools import cmp_to_key
from typing import Any

import httpx

from repo_man.formats.rpm.version import compare_versions
from repo_man.metrics import (
    cache_upstream_fetch_errors_total,
    packages_pulled_from_upstream_total,
    upstream_last_access_timestamp_seconds,
)
from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)

RPM_METADATA_PREFIX = "repodata/"


def _storage_prefix(upstream_id: str) -> str:
    return f"cache/{upstream_id}"


def _parse_rpm_filename(filename: str) -> tuple[str, str] | None:
    """Parse RPM filename to (package_name, version-release). Returns None if not parseable.
    Format: name-version-release.arch.rpm -> name, version-release.
    """
    if not filename.endswith(".rpm"):
        return None
    base = filename[:-4]  # drop .rpm
    if "." in base:
        # last segment is arch (e.g. x86_64, noarch)
        base = base.rsplit(".", 1)[0]
    if "-" not in base or base.count("-") < 2:
        return None
    # name-version-release
    name, version, release = base.rsplit("-", 2)
    return name, f"{version}-{release}"


def get_or_fetch(
    upstream_id: str,
    path_suffix: str,
    upstream_config: dict[str, Any],
    storage: StorageBackend,
    package_hash_store: Any = None,
) -> tuple[bytes | None, bool]:
    """
    Return bytes from cache or fetch from upstream. path_suffix is relative to repo root.
    Metadata (repodata/*): fetch and store with .fetched_at.
    Package (*.rpm): get or fetch and store.
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

    is_metadata = path_suffix.startswith(RPM_METADATA_PREFIX) or path_suffix == "repodata"
    if is_metadata:
        try:
            with httpx.Client(follow_redirects=True, timeout=60.0) as client:
                r = client.get(url)
                if r.status_code != 200:
                    cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
                    return (None, False)
                raw = r.content
        except Exception as e:
            cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
            logger.warning("RPM metadata fetch failed: upstream=%s path=%s error=%s", upstream_id, path_suffix, e)
            return (None, False)
        storage.put(key, raw)
        storage.put(key + ".fetched_at", str(time.time()).encode("utf-8"))
        upstream_last_access_timestamp_seconds.labels(upstream=upstream_id).set(time.time())
        return (raw, True)

    # Package path (*.rpm)
    stream = _attach_rpm_stream(upstream_id, path_suffix, url, storage, key)
    if stream is None:
        return (None, False)
    try:
        data = b"".join(stream.iter_chunks())
        return (data, stream.from_upstream)
    except Exception as e:
        logger.warning("RPM package stream failed: upstream=%s path=%s error=%s", upstream_id, path_suffix, e)
        return (None, False)
    finally:
        stream.close()


def attach_package_stream(
    upstream_id: str,
    path_suffix: str,
    upstream_config: dict[str, Any],
    storage: StorageBackend,
):
    """Attach to cached or in-flight RPM package stream."""
    prefix = _storage_prefix(upstream_id)
    key = f"{prefix}/{path_suffix}" if path_suffix else prefix
    base_url = (upstream_config.get("url") or upstream_config.get("base_url", "")).rstrip("/")
    if not path_suffix.endswith(".rpm"):
        return None
    if not base_url and not storage.exists(key):
        return None
    url = f"{base_url}/{path_suffix.lstrip('/')}" if base_url else ""
    return _attach_rpm_stream(upstream_id, path_suffix, url, storage, key)


def _attach_rpm_stream(
    upstream_id: str,
    path_suffix: str,
    url: str,
    storage: StorageBackend,
    key: str,
):
    from repo_man.formats.pull_through import UpstreamStream, get_or_attach_package_stream

    def fetch_upstream() -> UpstreamStream:
        timeout = httpx.Timeout(1800.0, connect=30.0)
        client = httpx.Client(follow_redirects=True, timeout=timeout)
        try:
            req = client.build_request("GET", url)
            r = client.send(req, stream=True)
            if r.status_code != 200:
                r.close()
                client.close()
                cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
                raise RuntimeError(f"upstream status {r.status_code}")
            cl_hdr = r.headers.get("content-length")
            content_length = int(cl_hdr) if cl_hdr and cl_hdr.isdigit() else None

            def chunks():
                try:
                    for chunk in r.iter_bytes(1024 * 1024):
                        yield chunk
                finally:
                    r.close()
                    client.close()

            return UpstreamStream(content_length=content_length, chunks=chunks())
        except Exception:
            client.close()
            raise

    def on_success() -> None:
        packages_pulled_from_upstream_total.labels(upstream=upstream_id).inc()
        upstream_last_access_timestamp_seconds.labels(upstream=upstream_id).set(time.time())
        logger.info("Saved RPM package: upstream=%s path=%s", upstream_id, path_suffix)

    def on_error(exc: BaseException) -> None:
        cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
        logger.warning("RPM package fetch failed: upstream=%s path=%s error=%s", upstream_id, path_suffix, exc)

    if storage.exists(key):
        return get_or_attach_package_stream(storage, key, fetch_upstream)
    if not url:
        return None
    return get_or_attach_package_stream(
        storage, key, fetch_upstream, on_success=on_success, on_error=on_error
    )


def list_cached_packages_by_name(
    storage: StorageBackend,
    upstream_id: str,
) -> dict[str, list[tuple[str, str]]]:
    """List cached .rpm paths under cache/upstream_id, grouped by package name. Returns name -> [(version-release, path)]."""
    prefix = _storage_prefix(upstream_id)
    by_name: dict[str, list[tuple[str, str]]] = {}
    for path in storage.list_prefix(prefix):
        if not path.endswith(".rpm"):
            continue
        parts = path.split("/")
        filename = parts[-1] if parts else ""
        parsed = _parse_rpm_filename(filename)
        if parsed is None:
            continue
        name, ver_rel = parsed
        by_name.setdefault(name, []).append((ver_rel, path))
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
                logger.info("Pruned RPM package: upstream=%s path=%s", upstream_id, path)
                removed += 1
    return removed
