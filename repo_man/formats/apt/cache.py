"""Pull-through cache: fetch metadata, get-or-fetch .deb, prune."""

from __future__ import annotations

import gzip
import logging
import os
import time
from functools import cmp_to_key
from typing import Any

import httpx

logger = logging.getLogger(__name__)

from repo_man.formats.apt.version import compare_versions
from repo_man.hash_store.base import PackageHashStore
from repo_man.metrics import (
    cache_package_hash_mismatch_total,
    cache_upstream_fetch_errors_total,
    packages_pulled_from_upstream_total,
    upstream_last_access_timestamp_seconds,
)
from repo_man.storage.base import StorageBackend


def _storage_prefix(upstream_id: str) -> str:
    return f"cache/{upstream_id}"


def _resolve_upstream_auth(
    upstream_config: dict[str, Any] | None,
) -> tuple[dict[str, str] | None, tuple[str, str] | None]:
    """
    Build request auth from upstream_config["auth"].
    Supports:
      - bearer: token or token_env
      - basic: username/password or username_env/password_env
    """
    if not isinstance(upstream_config, dict):
        return None, None
    auth_cfg = upstream_config.get("auth")
    if not isinstance(auth_cfg, dict):
        return None, None

    auth_type = str(auth_cfg.get("type", "")).strip().lower()
    if auth_type == "bearer":
        token = auth_cfg.get("token")
        token_env = auth_cfg.get("token_env")
        if not token and isinstance(token_env, str) and token_env.strip():
            token = os.environ.get(token_env)
        if isinstance(token, str) and token.strip():
            return {"Authorization": f"Bearer {token.strip()}"}, None
        return None, None

    if auth_type == "basic":
        username = auth_cfg.get("username")
        password = auth_cfg.get("password")
        username_env = auth_cfg.get("username_env")
        password_env = auth_cfg.get("password_env")
        if (username is None or username == "") and isinstance(username_env, str) and username_env.strip():
            username = os.environ.get(username_env)
        if (password is None or password == "") and isinstance(password_env, str) and password_env.strip():
            password = os.environ.get(password_env)
        if isinstance(username, str) and isinstance(password, str):
            return None, (username, password)
        return None, None

    return None, None


def parse_packages_for_hashes(raw: bytes) -> dict[str, str]:
    """
    Parse Packages or Packages.gz content; return path -> hash (SHA256 preferred, else MD5).
    Path is as in Filename (e.g. pool/main/.../foo.deb). Hash is normalized (strip whitespace).
    """
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return {}
    text = raw.decode("utf-8", errors="replace")
    result: dict[str, str] = {}
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        filename: str | None = None
        sha256: str | None = None
        md5: str | None = None
        for line in block.split("\n"):
            if line.startswith("Filename:"):
                filename = line.split(":", 1)[1].strip()
            elif line.startswith("SHA256:"):
                parts = line.split(":", 1)[1].strip().split()
                sha256 = parts[0] if parts else None
            elif line.startswith("MD5Sum:"):
                parts = line.split(":", 1)[1].strip().split()
                md5 = parts[0] if parts else None
            elif line.startswith(" ") and (sha256 is None and "SHA256" in line or md5 is None and "MD5Sum" in line):
                # Continuation line (multi-line hash)
                pass
        if filename:
            h = sha256 or md5
            if h:
                result[filename] = h
    return result


def _resolve_metadata_base_url(
    base_url: str,
    path: str,
    upstream_config: dict[str, Any] | None,
) -> str:
    """Select upstream base URL for metadata path."""
    normalized_path = path.lstrip("/")
    if normalized_path.startswith("meta-release"):
        if isinstance(upstream_config, dict):
            override = upstream_config.get("meta_release_base_url")
            if isinstance(override, str) and override.strip():
                return override.strip()
    return base_url


def fetch_metadata_from_upstream(
    base_url: str,
    path: str,
    upstream_config: dict[str, Any] | None = None,
) -> bytes | None:
    """Fetch a single file from upstream (e.g. Release, Packages.gz)."""
    effective_base_url = _resolve_metadata_base_url(base_url, path, upstream_config)
    url = effective_base_url.rstrip("/") + "/" + path.lstrip("/")
    headers, basic_auth = _resolve_upstream_auth(upstream_config)
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            r = client.get(url, headers=headers, auth=basic_auth)
            if r.status_code == 200:
                return r.content
            logger.warning("Metadata fetch failed: url=%s status=%s", url, r.status_code)
    except Exception as e:
        logger.warning("Metadata fetch failed: url=%s error=%s", url, e)
    return None


def cache_metadata(
    upstream_id: str,
    upstream_config: dict[str, Any],
    storage: StorageBackend,
    ttl_seconds: int | None = None,
) -> None:
    """
    Fetch Release (and optionally Packages) from upstream and store under cache/upstream_id/.
    If ttl_seconds is None, we don't cache long-term (proxy semantics); we still write for consistency.
    """
    base_url = upstream_config.get("url") or upstream_config.get("base_url", "")
    if not base_url:
        return
    prefix = _storage_prefix(upstream_id)
    layout = upstream_config.get("layout", "classic")
    if layout == "single-stream":
        release_path = "Release"
    else:
        release_path = "dists/default/Release"  # placeholder; real path from suite/component/arch
    content = fetch_metadata_from_upstream(base_url, release_path, upstream_config)
    if content:
        storage.put(f"{prefix}/Release", content)
        upstream_last_access_timestamp_seconds.labels(upstream=upstream_id).set(time.time())


def verify_and_update_package_hashes(
    upstream_id: str,
    path_hashes: dict[str, str],
    storage: StorageBackend,
    hash_store: PackageHashStore,
) -> None:
    """
    After fetching Packages/Packages.gz: compare new path->hash with stored hashes.
    If a cached package's hash changed on the remote, delete it from cache and increment metric.
    Update hash store to new hashes; remove entries for paths no longer in metadata.
    """
    prefix = _storage_prefix(upstream_id)
    # Paths that were in our store but not in new metadata -> remove from store and cache
    stored_paths = set(hash_store.list_paths(upstream_id))
    new_paths = set(path_hashes)
    for path in stored_paths - new_paths:
        hash_store.delete(upstream_id, path)
        cache_key = f"{prefix}/{path}"
        if storage.exists(cache_key):
            storage.delete(cache_key)
            logger.info("Dropped cached package (removed from metadata): upstream=%s path=%s", upstream_id, path)
    # Paths in new metadata: if we had a different hash, drop cache and update
    for path, new_hash in path_hashes.items():
        old_hash = hash_store.get(upstream_id, path)
        cache_key = f"{prefix}/{path}"
        if old_hash is not None and old_hash != new_hash:
            if storage.exists(cache_key):
                storage.delete(cache_key)
                cache_package_hash_mismatch_total.labels(upstream=upstream_id).inc()
                logger.warning(
                    "Dropped cached package (hash changed on remote): upstream=%s path=%s",
                    upstream_id,
                    path,
                )
        hash_store.set(upstream_id, path, new_hash)


def get_or_fetch(
    upstream_id: str,
    path_suffix: str,
    upstream_config: dict[str, Any],
    storage: StorageBackend,
    package_hash_store: PackageHashStore | None = None,
) -> tuple[bytes | None, bool]:
    """
    Single entry point for serve: return (data, from_upstream) for cache/<id>/path_suffix.
    Checks storage first; on miss fetches (metadata or package) from upstream and stores.
    """
    prefix = _storage_prefix(upstream_id)
    key = f"{prefix}/{path_suffix}" if path_suffix else prefix
    existing = storage.get(key)
    if existing is not None:
        return (existing, False)
    base_url = upstream_config.get("url") or upstream_config.get("base_url", "")
    if not base_url:
        return (None, False)
    if path_suffix.startswith("pool/"):
        relative_path = path_suffix
        data = get_or_fetch_package(upstream_id, relative_path, upstream_config, storage)
        return (data, data is not None)
    # Metadata path: fetch from upstream, store, optionally verify Packages hashes
    raw = fetch_metadata_from_upstream(base_url, path_suffix, upstream_config)
    if raw is None:
        cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
        return (None, False)
    storage.put(key, raw)
    storage.put(key + ".fetched_at", str(time.time()).encode("utf-8"))
    upstream_last_access_timestamp_seconds.labels(upstream=upstream_id).set(time.time())
    if (
        (path_suffix.endswith("Packages.gz") or (path_suffix.endswith("Packages") and not path_suffix.endswith("Packages.gz")))
        and package_hash_store is not None
    ):
        path_hashes = parse_packages_for_hashes(raw)
        if path_hashes:
            verify_and_update_package_hashes(upstream_id, path_hashes, storage, package_hash_store)
    return (raw, True)


def get_or_fetch_package(
    upstream_id: str,
    relative_path: str,
    upstream_config: dict[str, Any],
    storage: StorageBackend,
) -> bytes | None:
    """
    Return .deb bytes from cache or fetch from upstream, store, then return.
    relative_path is the path within the repo (e.g. pool/main/a/apt/apt_1.0_amd64.deb).
    """
    prefix = _storage_prefix(upstream_id)
    key = f"{prefix}/pool/{relative_path}" if not relative_path.startswith("pool/") else f"{prefix}/{relative_path}"
    existing = storage.get(key)
    if existing is not None:
        return existing
    base_url = upstream_config.get("url") or upstream_config.get("base_url", "")
    if not base_url:
        logger.warning("Package fetch skipped: upstream=%s path=%s no base_url", upstream_id, relative_path)
        return None
    url = base_url.rstrip("/") + "/" + relative_path.lstrip("/")
    headers, basic_auth = _resolve_upstream_auth(upstream_config)
    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            r = client.get(url, headers=headers, auth=basic_auth)
            if r.status_code == 200:
                storage.put(key, r.content)
                packages_pulled_from_upstream_total.labels(upstream=upstream_id).inc()
                upstream_last_access_timestamp_seconds.labels(upstream=upstream_id).set(time.time())
                logger.info("Saved package: upstream=%s package=%s", upstream_id, relative_path)
                return r.content
            cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
            logger.warning(
                "Package fetch failed: upstream=%s path=%s status=%s",
                upstream_id,
                relative_path,
                r.status_code,
            )
    except Exception as e:
        cache_upstream_fetch_errors_total.labels(upstream=upstream_id).inc()
        logger.warning("Package fetch failed: upstream=%s path=%s error=%s", upstream_id, relative_path, e)
    return None


def list_cached_packages_by_name(
    storage: StorageBackend,
    upstream_id: str,
) -> dict[str, list[tuple[str, str]]]:
    """
    List cached .deb paths under cache/upstream_id, grouped by package name.
    Returns dict: package_name -> [(version, storage_path), ...]
    """
    prefix = _storage_prefix(upstream_id)
    by_name: dict[str, list[tuple[str, str]]] = {}
    for path in storage.list_prefix(prefix):
        if not path.endswith(".deb"):
            continue
        # Path like cache/ubuntu/pool/main/a/apt/apt_1.0_amd64.deb - we need to parse version from path or from Packages
        # Simple approach: path segments; last is filename like apt_1.0_amd64.deb -> name=apt, version=1.0
        parts = path.split("/")
        filename = parts[-1] if parts else ""
        if "_" in filename and filename.endswith(".deb"):
            name_ver = filename[:-4].rsplit("_", 1)[0]  # apt_1.0_amd64 -> apt_1.0
            if "_" in name_ver:
                name, version = name_ver.rsplit("_", 1)
            else:
                name, version = name_ver, "0"
            by_name.setdefault(name, []).append((version, path))
    return by_name


def _sort_versions_desc(version_paths: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(version_paths, key=cmp_to_key(lambda a, b: -compare_versions(a[0], b[0])))


def prune_upstream(
    storage: StorageBackend,
    upstream_id: str,
    keep_versions_per_package: int,
) -> int:
    """
    For each package name, keep only the latest keep_versions_per_package versions (by Debian version order);
    delete the rest. Return number of files removed.
    Only touches cache/<upstream_id>/; published (e.g. local/) is never deleted.
    """
    by_name = list_cached_packages_by_name(storage, upstream_id)
    removed = 0
    for name, version_paths in by_name.items():
        if len(version_paths) <= keep_versions_per_package:
            continue
        sorted_paths = _sort_versions_desc(version_paths)
        for _, path in sorted_paths[keep_versions_per_package:]:
            if storage.delete(path):
                logger.info("Pruned package: upstream=%s path=%s", upstream_id, path)
                removed += 1
    return removed
