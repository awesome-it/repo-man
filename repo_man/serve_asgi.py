"""ASGI app that routes /api/v1 to FastAPI and serves repo paths (GET; scoped HEAD for do-release-upgrade)."""

from __future__ import annotations

import asyncio
import logging
from functools import partial
import time
from typing import Any, Callable, Iterator

from repo_man.formats.registry import get_backend
from repo_man.metrics import (
    cache_requests_total,
    get_metrics_output,
    http_request_duration_seconds,
    http_requests_total,
    packages_served_total,
)
from repo_man.http_upgrade_paths import (
    is_do_release_upgrade_head_path,
    is_meta_release_path,
    public_origin_from_headers,
    rewrite_meta_release_urls,
)
from repo_man.repo_service import RepoService
from repo_man.storage.base import StorageBackend

try:
    from repo_man.hash_store.base import PackageHashStore as _PackageHashStore
except ImportError:
    _PackageHashStore = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

_PACKAGE_SUFFIXES = (".deb", ".udeb", ".rpm", ".apk")


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


def _finalize_head_response(
    http_method: str,
    result: tuple[int, list[tuple[str, str]], bytes],
) -> tuple[int, list[tuple[str, str]], bytes]:
    """For HEAD, drop the body but keep Content-Length and other headers (RFC 9110)."""
    if http_method != "HEAD":
        return result
    status, headers, _body = result
    return status, headers, b""


def _content_type_for_key(key: str) -> str:
    if key.endswith(".gz"):
        return "application/gzip"
    if key.endswith((".deb", ".udeb")):
        return "application/vnd.debian.binary-package"
    if key.endswith(".rpm"):
        return "application/x-rpm"
    if key.endswith(".apk"):
        return "application/vnd.apk"
    return "application/octet-stream"


def _is_package_key(key: str) -> bool:
    return key.endswith(_PACKAGE_SUFFIXES)


def _attach_package_stream_for_key(
    key: str,
    storage: StorageBackend,
    upstreams: list[dict[str, Any]],
):
    """Resolve upstream and attach to a package pull-through stream. None if not applicable."""
    if not key.startswith("cache/") or not _is_package_key(key):
        return None
    parts = key.split("/", 2)
    if len(parts) < 3:
        return None
    upstream_id, suffix = parts[1], parts[2]
    upstream_config = next((u for u in upstreams if u.get("name") == upstream_id), None)
    if upstream_config is None:
        return None
    fmt = upstream_config.get("format", "apt")
    try:
        if fmt == "apt":
            from repo_man.formats.apt import cache as apt_cache

            return apt_cache.attach_package_stream(upstream_id, suffix, upstream_config, storage)
        if fmt == "rpm":
            from repo_man.formats.rpm import cache as rpm_cache

            return rpm_cache.attach_package_stream(upstream_id, suffix, upstream_config, storage)
        if fmt == "alpine":
            from repo_man.formats.alpine import cache as alpine_cache

            return alpine_cache.attach_package_stream(upstream_id, suffix, upstream_config, storage)
    except Exception as e:
        logger.warning("attach_package_stream failed: key=%s error=%s", key, e)
    return None


def _record_package_served(
    key: str,
    path_prefix: str,
    package_hash_store: Any,
    client_address: tuple[str, int] | None,
    forwarded_for: str | None,
    get_client_id_fn: Callable[[str], str],
) -> None:
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
    http_method: str = "GET",
    public_origin: str | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    """
    Handle a GET or (allowlisted) HEAD request; returns (status_code, headers, body).
    Used by both the legacy HTTP handler and the ASGI app for non-streaming responses.

    Package pulls should prefer the ASGI streaming path; this still supports buffered
    legacy serve via pull-through (joins stream chunks).
    """
    start = time.perf_counter()
    path_prefix = "/"
    method_label = http_method.upper() if http_method else "GET"
    try:
        path_stripped = (path or "").strip("/")
        if path_stripped.startswith("api/"):
            path_prefix = "/api"
            if not enable_api:
                http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="404").inc()
                return _finalize_head_response(http_method, _error_response(404, "Not found"))
            if not path_stripped.startswith("api/v1/"):
                http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="404").inc()
                return _finalize_head_response(http_method, _error_response(404, "Not found"))
            http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="404").inc()
            return _finalize_head_response(http_method, _error_response(404, "Not found"))

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
            if http_method == "HEAD":
                http_requests_total.labels(method=method_label, path_prefix="/metrics", status="404").inc()
                return _finalize_head_response(http_method, _error_response(404, "Not found"))
            content = (metrics_callback or get_metrics_output)()
            body = content.encode("utf-8")
            http_requests_total.labels(method=method_label, path_prefix="/metrics", status="200").inc()
            return _finalize_head_response(
                http_method,
                (
                    200,
                    [
                        ("Content-Type", "text/plain; charset=utf-8"),
                        ("Content-Length", str(len(body))),
                    ],
                    body,
                ),
            )
        if key is None:
            logger.debug("Not found: path_prefix=%s path=%s", path_prefix, path)
            http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="404").inc()
            return _finalize_head_response(http_method, _error_response(404, "Not found"))

        # Package path: use pull-through attach (buffered join for this legacy API)
        if key.startswith("cache/") and _is_package_key(key):
            stream = _attach_package_stream_for_key(key, storage, upstreams)
            if stream is None and not storage.exists(key):
                # Fall through to generic get_or_fetch for unusual layouts
                pass
            elif stream is not None:
                from_upstream = stream.from_upstream
                try:
                    data = b"".join(stream.iter_chunks())
                except Exception:
                    data = None
                finally:
                    stream.close()
                if data is None:
                    cache_requests_total.labels(result="miss").inc()
                    http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="404").inc()
                    return _finalize_head_response(http_method, _error_response(404, "Not found"))
                headers = [
                    ("Content-Type", _content_type_for_key(key)),
                    ("Content-Length", str(len(data))),
                ]
                cache_requests_total.labels(result="miss" if from_upstream else "hit").inc()
                http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="200").inc()
                if http_method != "HEAD":
                    _record_package_served(
                        key, path_prefix, package_hash_store, client_address, forwarded_for, get_client_id_fn
                    )
                return _finalize_head_response(http_method, (200, headers, data))

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
        if data is None:
            if key.startswith("cache/"):
                cache_requests_total.labels(result="miss").inc()
            logger.debug("Not found: path_prefix=%s key=%s", path_prefix, key)
            http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="404").inc()
            return _finalize_head_response(http_method, _error_response(404, "Not found"))
        if key.startswith("cache/"):
            cache_requests_total.labels(result="hit" if not served_from_upstream else "miss").inc()
        if is_meta_release_path(path) and public_origin and key.startswith("cache/"):
            parts = key.split("/", 2)
            upstream_id = parts[1] if len(parts) >= 2 else None
            rewrite_prefix = path_prefix
            for u in upstreams:
                if u.get("name") == upstream_id:
                    rewrite_prefix = (u.get("path_prefix") or "/").rstrip("/") or "/"
                    break
            data = rewrite_meta_release_urls(data, public_origin, rewrite_prefix)
        headers = [
            ("Content-Type", _content_type_for_key(key)),
            ("Content-Length", str(len(data))),
        ]
        http_requests_total.labels(method=method_label, path_prefix=path_prefix, status="200").inc()
        if http_method != "HEAD" and _is_package_key(key):
            _record_package_served(
                key, path_prefix, package_hash_store, client_address, forwarded_for, get_client_id_fn
            )
        return _finalize_head_response(http_method, (200, headers, data))
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
    """Build the ASGI app that routes /api/v1 to FastAPI and serves GET (and scoped HEAD) for repo paths."""
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
        if enable_api and fastapi_app is not None and (
            path.startswith("/api/v1") or path == "/api/publish"
        ):
            await fastapi_app(scope, receive, send)
            return
        if (path.startswith("/api/v1") or path == "/api/publish") and not enable_api:
            await _send_http_response(send, 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found\n")
            return
        if method not in ("GET", "HEAD"):
            await _send_http_response(send, 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found\n")
            return
        if method == "HEAD" and not is_do_release_upgrade_head_path(path):
            await _send_http_response(send, 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found\n")
            return
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
        host: str | None = None
        forwarded_proto: str | None = None
        forwarded_host: str | None = None
        for name, value in (scope.get("headers") or []):
            lower = name.lower()
            try:
                decoded = value.decode("latin-1").strip()
            except Exception:
                continue
            if lower == b"x-forwarded-for":
                forwarded_for = decoded or None
            elif lower == b"host":
                host = decoded or None
            elif lower == b"x-forwarded-proto":
                forwarded_proto = decoded or None
            elif lower == b"x-forwarded-host":
                forwarded_host = decoded or None
        public_origin = public_origin_from_headers(
            host,
            scheme=str(scope.get("scheme") or "http"),
            forwarded_proto=forwarded_proto,
            forwarded_host=forwarded_host,
        )

        # Resolve path; stream package bodies without buffering the full object.
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
        key, path_prefix = await asyncio.get_running_loop().run_in_executor(
            None, lambda: service.resolve(path)
        )
        if key is not None and key.startswith("cache/") and _is_package_key(key) and method == "GET":
            stream = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: _attach_package_stream_for_key(key, storage, upstreams),
            )
            if stream is not None:
                headers = [("Content-Type", _content_type_for_key(key))]
                if stream.content_length is not None:
                    headers.append(("Content-Length", str(stream.content_length)))
                http_requests_total.labels(method="GET", path_prefix=path_prefix, status="200").inc()
                cache_requests_total.labels(result="miss" if stream.from_upstream else "hit").inc()
                _record_package_served(
                    key, path_prefix, package_hash_store, client, forwarded_for, get_client_id_fn
                )
                try:
                    await _send_http_stream(send, receive, 200, headers, stream.iter_chunks(), stream.close)
                finally:
                    http_request_duration_seconds.labels(path_prefix=path_prefix).observe(
                        time.perf_counter() - start
                    )
                return
            if not storage.exists(key):
                http_requests_total.labels(method="GET", path_prefix=path_prefix, status="404").inc()
                cache_requests_total.labels(result="miss").inc()
                http_request_duration_seconds.labels(path_prefix=path_prefix).observe(
                    time.perf_counter() - start
                )
                await _send_http_response(
                    send, 404, [("Content-Type", "text/plain; charset=utf-8")], b"Not found\n"
                )
                return

        loop = asyncio.get_running_loop()
        status, headers, body = await loop.run_in_executor(
            None,
            partial(
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
                http_method=method,
                public_origin=public_origin,
            ),
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


async def _send_http_stream(
    send: Any,
    receive: Any,
    status: int,
    headers: list[tuple[str, str]],
    chunks: Iterator[bytes],
    on_close: Callable[[], None] | None = None,
) -> None:
    """
    Stream response body chunks. Client disconnect stops socket writes only;
    ``on_close`` unsubscribes the client without cancelling the upstream fill.
    """
    h = [(k.encode("ascii"), v.encode("ascii")) for k, v in headers]
    await send({"type": "http.response.start", "status": status, "headers": h})
    disconnected = False

    async def _watch_disconnect() -> None:
        nonlocal disconnected
        try:
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    disconnected = True
                    logger.info("Client disconnected during package stream; cache fill continues")
                    return
        except Exception:
            disconnected = True

    watch = asyncio.create_task(_watch_disconnect())
    loop = asyncio.get_running_loop()
    try:
        while True:
            if disconnected:
                break
            try:
                chunk = await loop.run_in_executor(None, lambda: next(chunks, None))
            except Exception as e:
                logger.warning("Package stream error: %s", e)
                break
            if chunk is None:
                break
            if disconnected:
                break
            try:
                await send({"type": "http.response.body", "body": chunk, "more_body": True})
            except Exception:
                disconnected = True
                logger.info("Client write failed during package stream; cache fill continues")
                break
        if not disconnected:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
    finally:
        watch.cancel()
        try:
            await watch
        except asyncio.CancelledError:
            pass
        if on_close is not None:
            try:
                on_close()
            except Exception:
                pass
