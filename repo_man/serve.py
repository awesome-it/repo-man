"""HTTP server that serves APT repo from storage and /metrics. Pull-through: fetch from upstream on miss."""

from __future__ import annotations

import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable
from urllib.parse import unquote

from repo_man.disk import free_disk_until_under_watermark
from repo_man.formats.registry import get_backend
from repo_man.metrics import (
    cache_requests_total,
    cache_upstream_fetch_errors_total,
    client_last_served_timestamp_seconds,
    client_packages_served_total,
    get_metrics_output,
    http_request_duration_seconds,
    http_requests_total,
    packages_served_total,
    upstream_last_access_timestamp_seconds,
)
from repo_man.storage.base import StorageBackend

try:
    from repo_man.hash_store.base import PackageHashStore as _PackageHashStore
except ImportError:
    _PackageHashStore = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)
_metrics_callback: Callable[[], str] | None = None

# Client tracking: reverse DNS cache (ip -> hostname or ip); per-client stats via Prometheus only
_reverse_dns_cache: dict[str, str] = {}
_cache_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="repo_man_reverse_dns")

_REVERSE_LOOKUP_TIMEOUT = 1.0


def _reverse_lookup(ip: str) -> None:
    """Background: resolve IP to hostname; on success or failure update cache (fall back to IP)."""
    try:
        hostname, _, _ = socket.gethostbyaddr(ip)
        with _cache_lock:
            _reverse_dns_cache[ip] = hostname
    except Exception:
        with _cache_lock:
            _reverse_dns_cache[ip] = ip


def _get_client_id(ip: str) -> str:
    """Return client id (hostname or IP). Never blocks; on first see use IP and enqueue reverse lookup."""
    with _cache_lock:
        if ip in _reverse_dns_cache:
            return _reverse_dns_cache[ip]
        _reverse_dns_cache[ip] = ip
    _executor.submit(_reverse_lookup, ip)
    return ip


def set_metrics_callback(cb: Callable[[], str] | None = None) -> None:
    global _metrics_callback
    _metrics_callback = cb or get_metrics_output


def _default_metrics() -> str:
    return get_metrics_output()


class RepoHTTPRequestHandler(BaseHTTPRequestHandler):
    """Serves repo files from storage and /metrics."""

    storage: StorageBackend
    upstreams: list[dict[str, Any]]  # name, path_prefix
    local_prefixes: list[str]  # path prefixes that are local repos (e.g. "local")
    metadata_ttl_seconds: int = 0  # 0 = no TTL; cached metadata re-fetched when older than this
    package_hash_store: _PackageHashStore | None = None  # optional; when set, verify package hashes on metadata fetch
    disk_high_watermark_bytes: int | None = None  # when set, auto-prune cache when usage exceeds this
    get_disk_usage_fn: Callable[[], int] | None = None  # used with disk_high_watermark_bytes
    keep_versions_per_package: int = 0  # when > 0, auto-prune to keep this many versions per package after each cache write

    def _maybe_prune_old_versions(self) -> None:
        """Keep only the latest keep_versions_per_package versions per package for each upstream."""
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
                pass
        if total_removed:
            logger.info(
                "Auto-pruned %s cached package(s) (keep %s version(s) per package)",
                total_removed,
                self.keep_versions_per_package,
            )

    def _maybe_free_disk_over_watermark(self) -> None:
        """If over disk high watermark, free cache (evict by oldest last_served when hash_store set)."""
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

    def _find_upstream_by_prefix(self, path_prefix: str) -> dict | None:
        for u in self.upstreams:
            p = (u.get("path_prefix") or "/").rstrip("/") or "/"
            if path_prefix == p or path_prefix.startswith(p + "/"):
                return u
        return None

    def _get_storage_key(self, path: str) -> str | None:
        path = unquote(path).strip("/")
        if not path:
            return None
        if path == "metrics":
            return "METRICS"
        # Match shortest path_prefix so we get the full suffix for storage key
        parts = path.split("/")
        for i in range(1, len(parts) + 1):
            prefix = "/" + "/".join(parts[:i])
            storage_prefix = self._path_prefix_to_storage_prefix(prefix)
            if storage_prefix:
                suffix = "/".join(parts[i:]) if i < len(parts) else ""
                if storage_prefix == "METRICS":
                    return "METRICS"
                key = f"{storage_prefix}/{suffix}" if suffix else storage_prefix
                return key
        return None

    def _path_prefix_for_metrics(self) -> str:
        path = (self.path or "").strip("/")
        if path == "metrics":
            return "/metrics"
        parts = path.split("/")
        return "/" + (parts[0] if parts else "")

    def do_GET(self) -> None:
        path_prefix = self._path_prefix_for_metrics()
        start = time.perf_counter()
        try:
            key = self._get_storage_key(self.path)
            if key == "METRICS":
                content = (_metrics_callback or _default_metrics)()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(content.encode("utf-8"))))
                self.end_headers()
                self.wfile.write(content.encode("utf-8"))
                http_requests_total.labels(method="GET", path_prefix="/metrics", status="200").inc()
                return
            if key is None:
                logger.debug("Not found: path_prefix=%s path=%s", path_prefix, self.path)
                self.send_error(404, "Not found")
                http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
                return
            data = self.storage.get(key)
            # If cached metadata is past TTL, treat as stale so we refetch (any path not a package file)
            if (
                data is not None
                and key.startswith("cache/")
                and self.metadata_ttl_seconds > 0
            ):
                if not (key.endswith(".deb") or key.endswith(".rpm") or key.endswith(".apk")):
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
                    # So backend.get_or_fetch will refetch: remove stale cache entry
                    if data is None:
                        self.storage.delete(key)
                        self.storage.delete(key + ".fetched_at")
            served_from_upstream = False
            if data is None and key.startswith("cache/"):
                parts = key.split("/", 2)
                if len(parts) >= 3:
                    upstream_id, suffix = parts[1], parts[2]
                    upstream_config = next(
                        (u for u in self.upstreams if u.get("name") == upstream_id),
                        None,
                    )
                    if upstream_config:
                        fmt = upstream_config.get("format", "apt")
                        try:
                            backend = get_backend(fmt)
                            data, served_from_upstream = backend.get_or_fetch(
                                upstream_id,
                                suffix,
                                upstream_config,
                                self.storage,
                                self.package_hash_store,
                            )
                        except ValueError:
                            pass
            if served_from_upstream:
                self._maybe_prune_old_versions()
                self._maybe_free_disk_over_watermark()
            if data is None:
                if key.startswith("cache/"):
                    cache_requests_total.labels(result="miss").inc()
                logger.debug("Not found: path_prefix=%s key=%s", path_prefix, key)
                self.send_error(404, "Not found")
                http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
                return
            if key.startswith("cache/"):
                cache_requests_total.labels(result="hit" if not served_from_upstream else "miss").inc()
            self.send_response(200)
            if key.endswith(".gz"):
                self.send_header("Content-Type", "application/gzip")
            elif key.endswith(".deb"):
                self.send_header("Content-Type", "application/vnd.debian.binary-package")
            elif key.endswith(".rpm"):
                self.send_header("Content-Type", "application/x-rpm")
            elif key.endswith(".apk"):
                self.send_header("Content-Type", "application/vnd.apk")
            else:
                self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            http_requests_total.labels(method="GET", path_prefix=path_prefix, status="200").inc()
            if key.endswith((".deb", ".rpm", ".apk")):
                packages_served_total.labels(path_prefix=path_prefix).inc()
                source = "upstream" if served_from_upstream else "cache"
                logger.info("Served package: path_prefix=%s source=%s package=%s", path_prefix, source, key)
                # Record last_served for watermark eviction (oldest-first drop)
                if self.package_hash_store is not None:
                    parts_key = key.split("/", 2)
                    if len(parts_key) >= 3:
                        self.package_hash_store.set_last_served(parts_key[1], parts_key[2], time.time())
                # Track client in Prometheus only (client = IP or hostname from reverse DNS)
                try:
                    client_ip = self.client_address[0] if self.client_address else None
                    if client_ip:
                        client_id = _get_client_id(client_ip)
                        now = time.time()
                        client_packages_served_total.labels(client=client_id).inc()
                        client_last_served_timestamp_seconds.labels(client=client_id).set(now)
                except Exception:
                    pass
            else:
                source = "upstream" if served_from_upstream else "cache"
                if source == "cache" and key.startswith("cache/") and self.metadata_ttl_seconds > 0:
                    fetched_at_bytes = self.storage.get(key + ".fetched_at")
                    if fetched_at_bytes is not None:
                        try:
                            fetched_at = float(fetched_at_bytes.decode("utf-8").strip())
                            expiry_at = fetched_at + self.metadata_ttl_seconds
                            time_until_expiry = max(0.0, expiry_at - time.time())
                            logger.info(
                                "Served metadata from cache: path_prefix=%s key=%s time_until_expiry_seconds=%.0f",
                                path_prefix,
                                key,
                                time_until_expiry,
                            )
                        except (ValueError, UnicodeDecodeError):
                            logger.info("Served metadata: path_prefix=%s source=%s key=%s", path_prefix, source, key)
                    else:
                        logger.info("Served metadata: path_prefix=%s source=%s key=%s", path_prefix, source, key)
                else:
                    logger.info("Served metadata: path_prefix=%s source=%s key=%s", path_prefix, source, key)
        except (BrokenPipeError, ConnectionResetError) as e:
            # Client closed the connection before we finished sending (e.g. apt/dnf cancelled)
            logger.debug("Client closed connection before response completed: %s", e)
        finally:
            http_request_duration_seconds.labels(path_prefix=path_prefix).observe(time.perf_counter() - start)

    def log_message(self, format: str, *args: Any) -> None:
        # Quiet logging by default; can be overridden
        pass


def run_server(
    bind: str,
    port: int,
    storage: StorageBackend,
    upstreams: list[dict[str, Any]],
    local_prefixes: list[str] | None = None,
    metadata_ttl_seconds: int = 0,
    package_hash_store: _PackageHashStore | None = None,
    disk_high_watermark_bytes: int | None = None,
    get_disk_usage_fn: Callable[[], int] | None = None,
    keep_versions_per_package: int = 0,
) -> None:
    """Run HTTP server until interrupted."""
    local_prefixes = local_prefixes or []
    handler = type("Handler", (RepoHTTPRequestHandler,), {
        "storage": storage,
        "upstreams": upstreams,
        "local_prefixes": local_prefixes,
        "metadata_ttl_seconds": metadata_ttl_seconds,
        "package_hash_store": package_hash_store,
        "disk_high_watermark_bytes": disk_high_watermark_bytes,
        "get_disk_usage_fn": get_disk_usage_fn,
        "keep_versions_per_package": keep_versions_per_package,
    })
    server = HTTPServer((bind, port), handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
