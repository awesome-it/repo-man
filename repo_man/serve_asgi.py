"""ASGI app that routes /api/v1 to FastAPI and serves repo/GET otherwise."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

from repo_man.formats.registry import get_backend
from repo_man.metrics import (
    cache_requests_total,
    get_metrics_output,
    http_request_duration_seconds,
    http_requests_total,
    packages_served_total,
)
from repo_man.repo_service import RepoService
from repo_man.storage.base import StorageBackend

try:
    from repo_man.hash_store.base import PackageHashStore as _PackageHashStore
except ImportError:
    _PackageHashStore = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)


def _get_first_x_forwarded_for(forwarded_for: str | None) -> str | None:
    """
    Return the first IP from an X-Forwarded-For header value.

    If header contains multiple entries (comma-separated), we treat the first as the original client.
    """
    if not forwarded_for:
        return None
    first = forwarded_for.split(",", 1)[0].strip()
    return first or None


def _error_response(status: int, message: str = "") -> tuple[int, list[tuple[str, str]], bytes]:
    body = (message or f"{status}").encode("utf-8")
    headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    return status, headers, body


def handle_get_response(
    path: str,
    client_address: tuple[str, int] | None,
    forwarded_for: str | None,
    storage: StorageBackend,
    upstreams: list[dict[str, Any]],
    local_prefixes: list[str],
    metadata_ttl_seconds: int,
    package_hash_store: Any,
    disk_high_watermark_bytes: int | None,
    get_disk_usage_fn: Callable[[], int] | None,
    keep_versions_per_package: int,
    enable_api: bool,
    metrics_callback: Callable[[], str] | None,
    get_client_id_fn: Callable[[str], str],
) -> tuple[int, list[tuple[str, str]], bytes]:
    """
    Handle a GET request; returns (status_code, headers, body).
    Used by both the legacy HTTP handler and the ASGI app.
    """
    start = time.perf_counter()
    path_prefix = "/"
    try:
        path_stripped = (path or "").strip("/")
        # When API is disabled, any /api/ path returns 404. When enabled, /api/v1 is handled by FastAPI; other /api/ GETs 404.
        if path_stripped.startswith("api/"):
            path_prefix = "/api"
            if not enable_api:
                http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
                return _error_response(404, "Not found")
            if not path_stripped.startswith("api/v1/"):
                http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
                return _error_response(404, "Not found")
            # Should not reach here for /api/v1 - ASGI routes that to FastAPI
            http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
            return _error_response(404, "Not found")

        service = RepoService(
            storage,
            upstreams,
            local_prefixes,
            metadata_ttl_seconds,
            package_hash_store,
            disk_high_watermark_bytes,
            get_disk_usage_fn,
            keep_versions_per_package,
        )
        key, path_prefix = service.resolve(path)
        if key == "METRICS":
            content = (metrics_callback or get_metrics_output)()
            body = content.encode("utf-8")
            http_requests_total.labels(method="GET", path_prefix="/metrics", status="200").inc()
            return 200, [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ], body
        if key is None:
            logger.debug("Not found: path_prefix=%s path=%s", path_prefix, path)
            http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
            return _error_response(404, "Not found")
        data = storage.get(key)
        data = service.maybe_refresh_metadata_ttl(key, data)
        served_from_upstream = False
        if data is None and key.startswith("cache/"):
            parts = key.split("/", 2)
            if len(parts) >= 3:
                upstream_id, suffix = parts[1], parts[2]
                upstream_config = next(
                    (u for u in upstreams if u.get("name") == upstream_id),
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
                            storage,
                            package_hash_store,
                        )
                    except ValueError:
                        pass
        if served_from_upstream:
            # Prune/watermark maintenance runs in a background loop, not on request path.
            pass
        if data is None:
            if key.startswith("cache/"):
                cache_requests_total.labels(result="miss").inc()
            logger.debug("Not found: path_prefix=%s key=%s", path_prefix, key)
            http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
            return _error_response(404, "Not found")
        if key.startswith("cache/"):
            cache_requests_total.labels(result="hit" if not served_from_upstream else "miss").inc()
        if key.endswith(".gz"):
            content_type = "application/gzip"
        elif key.endswith(".deb"):
            content_type = "application/vnd.debian.binary-package"
        elif key.endswith(".rpm"):
            content_type = "application/x-rpm"
        elif key.endswith(".apk"):
            content_type = "application/vnd.apk"
        else:
            content_type = "application/octet-stream"
        headers = [
            ("Content-Type", content_type),
            ("Content-Length", str(len(data))),
        ]
        http_requests_total.labels(method="GET", path_prefix=path_prefix, status="200").inc()
        if key.endswith((".deb", ".rpm", ".apk")):
            packages_served_total.labels(path_prefix=path_prefix).inc()
            if package_hash_store is not None:
                parts_key = key.split("/", 2)
                if len(parts_key) >= 3:
                    package_hash_store.set_last_served(parts_key[1], parts_key[2], time.time())
            if client_address:
                try:
                    client_ip = _get_first_x_forwarded_for(forwarded_for) or client_address[0]
                    client_id = get_client_id_fn(client_ip)
                    from repo_man.metrics import client_packages_served_total, client_last_served_timestamp_seconds
                    client_packages_served_total.labels(client=client_id).inc()
                    client_last_served_timestamp_seconds.labels(client=client_id).set(time.time())
                except Exception:
                    pass
        return 200, headers, data
    finally:
        http_request_duration_seconds.labels(path_prefix=path_prefix).observe(time.perf_counter() - start)


def make_asgi_app(
    storage: StorageBackend,
    upstreams: list[dict[str, Any]],
    local_prefixes: list[str],
    metadata_ttl_seconds: int,
    package_hash_store: Any,
    disk_high_watermark_bytes: int | None,
    get_disk_usage_fn: Callable[[], int] | None,
    keep_versions_per_package: int,
    enable_api: bool,
    metrics_callback: Callable[[], str] | None,
    get_client_id_fn: Callable[[str], str],
):
    """Build the ASGI app that routes /api/v1 to FastAPI and serves GET for repo paths."""
    from repo_man.api import create_api_app
    from repo_man.serve import set_metrics_callback

    set_metrics_callback(metrics_callback)
    fastapi_app = create_api_app(storage) if enable_api else None

    async def repo_asgi(scope: dict, receive: object, send: object) -> None:
        if scope.get("type") != "http":
            return
        start = time.perf_counter()
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        # Route /api/v1 and legacy /api/publish to FastAPI when API is enabled
        if enable_api and fastapi_app is not None and (
            path.startswith("/api/v1") or path == "/api/publish"
        ):
            await fastapi_app(scope, receive, send)
            return
        if (path.startswith("/api/v1") or path == "/api/publish") and not enable_api:
            await _send_http_response(send, 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found\n")
            return
        if method != "GET":
            await _send_http_response(send, 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found\n")
            return
        # Fast-path /metrics so it does not depend on worker thread availability.
        if path == "/metrics":
            content = (metrics_callback or get_metrics_output)()
            body = content.encode("utf-8")
            headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ]
            http_requests_total.labels(method="GET", path_prefix="/metrics", status="200").inc()
            http_request_duration_seconds.labels(path_prefix="/metrics").observe(time.perf_counter() - start)
            await _send_http_response(send, 200, headers, body)
            return
        client = scope.get("client") or ("", 0)
        forwarded_for: str | None = None
        # scope["headers"] is a list of (name, value) where both are bytes.
        for name, value in (scope.get("headers") or []):
            if name.lower() == b"x-forwarded-for":
                try:
                    forwarded_for = value.decode("latin-1").strip()  # headers are ASCII-ish
                except Exception:
                    forwarded_for = None
                break
        loop = asyncio.get_running_loop()
        status, headers, body = await loop.run_in_executor(
            None,
            handle_get_response,
            path,
            client,
            forwarded_for,
            storage,
            upstreams,
            local_prefixes,
            metadata_ttl_seconds,
            package_hash_store,
            disk_high_watermark_bytes,
            get_disk_usage_fn,
            keep_versions_per_package,
            enable_api,
            metrics_callback,
            get_client_id_fn,
        )
        await _send_http_response(send, status, headers, body)

    return repo_asgi


async def _send_http_response(
    send: Any,
    status: int,
    headers: list[tuple[str, str]],
    body: bytes,
) -> None:
    h = [(k.encode("ascii"), v.encode("ascii")) for k, v in headers]
    await send({"type": "http.response.start", "status": status, "headers": h})
    await send({"type": "http.response.body", "body": body})
