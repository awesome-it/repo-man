"""HTTP server that serves APT repo from storage and /metrics. Pull-through: fetch from upstream on miss."""

from __future__ import annotations

import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable

from repo_man.formats.registry import get_backend
from repo_man.metrics import (
    cache_requests_total,
    client_last_served_timestamp_seconds,
    client_packages_served_total,
    get_metrics_output,
    http_request_duration_seconds,
    http_requests_total,
    packages_served_total,
)
from repo_man.storage.base import StorageBackend
from repo_man.repo_service import RepoService
from repo_man.serve_asgi import handle_get_response

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
    enable_api: bool = False  # when True, /api/v1 (FastAPI) is enabled

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
        # Delegate to RepoService helper (kept for backward compatibility)
        service = RepoService(
            self.storage,
            self.upstreams,
            self.local_prefixes,
            self.metadata_ttl_seconds,
            self.package_hash_store,
            self.disk_high_watermark_bytes,
            self.get_disk_usage_fn,
            self.keep_versions_per_package,
        )
        service.maybe_free_disk_over_watermark()

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

    def do_GET(self) -> None:
        try:
            status, headers, body = handle_get_response(
                self.path,
                self.client_address,
                self.storage,
                self.upstreams,
                self.local_prefixes,
                self.metadata_ttl_seconds,
                self.package_hash_store,
                self.disk_high_watermark_bytes,
                self.get_disk_usage_fn,
                self.keep_versions_per_package,
                self.enable_api,
                _metrics_callback or _default_metrics,
                _get_client_id,
            )
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError) as e:
            logger.debug("Client closed connection before response completed: %s", e)

    def do_POST(self) -> None:
        start = time.perf_counter()
        path_prefix = (self.path or "").strip("/") or "/"
        if not path_prefix.startswith("/"):
            path_prefix = "/" + path_prefix
        try:
            self.send_error(404, "Not found")
            http_requests_total.labels(method="POST", path_prefix=path_prefix, status="404").inc()
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
    enable_api: bool = False,
) -> None:
    """Run ASGI server (uvicorn) until interrupted. /api/v1 is FastAPI; other paths serve repo and /metrics."""
    import uvicorn
    from repo_man.serve_asgi import make_asgi_app
    local_prefixes = local_prefixes or []
    app = make_asgi_app(
        storage,
        upstreams,
        local_prefixes,
        metadata_ttl_seconds,
        package_hash_store,
        disk_high_watermark_bytes,
        get_disk_usage_fn,
        keep_versions_per_package,
        enable_api,
        _metrics_callback or _default_metrics,
        _get_client_id,
    )
    config = uvicorn.Config(app, host=bind, port=port, log_level="info")
    server = uvicorn.Server(config)
    server.run()
