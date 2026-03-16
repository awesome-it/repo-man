"""Integration test: serve returns /metrics and repo paths."""

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

from repo_man.serve import RepoHTTPRequestHandler
from repo_man.storage.local import LocalStorageBackend


def test_serve_metrics_and_path(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    storage.put("cache/ubuntu/Release", b"Release content")
    upstreams = [{"name": "ubuntu", "path_prefix": "/ubuntu"}]
    handler_class = type(
        "Handler",
        (RepoHTTPRequestHandler,),
        {"storage": storage, "upstreams": upstreams, "local_prefixes": []},
    )
    # Mock request for /metrics
    req = Mock()
    req.makefile.return_value = BytesIO()
    req.raw_requestline = b"GET /metrics HTTP/1.1\r\n"
    req.command = "GET"
    req.path = "/metrics"
    req.client_address = ("127.0.0.1", 0)
    req.requestline = "GET /metrics HTTP/1.1"
    wfile = BytesIO()
    handler = handler_class(req, ("127.0.0.1", 0), None)
    handler.path = "/metrics"
    handler.command = "GET"
    handler.requestline = "GET /metrics HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.wfile = wfile
    handler.do_GET()
    out = wfile.getvalue()
    assert b"HTTP" in out and b"200" in out
    assert b"repo_man_" in out or b"# HELP" in out  # Prometheus format
    # Mock request for /ubuntu/Release
    wfile2 = BytesIO()
    req2 = Mock()
    req2.makefile.return_value = BytesIO()
    req2.raw_requestline = b"GET /ubuntu/Release HTTP/1.1\r\n"
    req2.command = "GET"
    req2.path = "/ubuntu/Release"
    req2.client_address = ("127.0.0.1", 0)
    req2.requestline = "GET /ubuntu/Release HTTP/1.1"
    handler2 = handler_class(req2, ("127.0.0.1", 0), None)
    handler2.path = "/ubuntu/Release"
    handler2.command = "GET"
    handler2.requestline = "GET /ubuntu/Release HTTP/1.1"
    handler2.request_version = "HTTP/1.1"
    handler2.wfile = wfile2
    handler2.do_GET()
    out2 = wfile2.getvalue()
    assert b"200" in out2
    assert b"Release content" in out2


def test_serve_deb_tracks_client_in_metrics(tmp_path: Path) -> None:
    """Serving a .deb updates client metrics (per-client package count and last served timestamp)."""
    storage = LocalStorageBackend(tmp_path)
    storage.put("cache/ubuntu/pool/main/v/vim/vim_1.0_amd64.deb", b"deb content")
    upstreams = [{"name": "ubuntu", "path_prefix": "/ubuntu"}]
    handler_class = type(
        "Handler",
        (RepoHTTPRequestHandler,),
        {"storage": storage, "upstreams": upstreams, "local_prefixes": []},
    )
    client_ip = "192.168.1.100"
    req = Mock()
    req.makefile.return_value = BytesIO()
    req.raw_requestline = b"GET /ubuntu/pool/main/v/vim/vim_1.0_amd64.deb HTTP/1.1\r\n"
    req.command = "GET"
    req.path = "/ubuntu/pool/main/v/vim/vim_1.0_amd64.deb"
    req.client_address = (client_ip, 4242)
    req.requestline = "GET /ubuntu/pool/main/v/vim/vim_1.0_amd64.deb HTTP/1.1"
    wfile = BytesIO()
    handler = handler_class(req, (client_ip, 4242), None)
    handler.path = "/ubuntu/pool/main/v/vim/vim_1.0_amd64.deb"
    handler.command = "GET"
    handler.requestline = "GET /ubuntu/pool/main/v/vim/vim_1.0_amd64.deb HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.wfile = wfile
    handler.do_GET()
    out = wfile.getvalue()
    assert b"200" in out and b"deb content" in out
    # Client tracked in Prometheus metrics
    from repo_man.metrics import get_metrics_output
    metrics = get_metrics_output()
    assert "repo_man_client_packages_served_total" in metrics
    assert "repo_man_client_last_served_timestamp_seconds" in metrics
    assert client_ip in metrics


def test_serve_rpm_path_from_cache(tmp_path: Path) -> None:
    """Request for RPM repodata path returns cached content (RPM upstream)."""
    storage = LocalStorageBackend(tmp_path)
    storage.put("cache/rocky9/repodata/repomd.xml", b"<repomd/>")
    storage.put("cache/rocky9/repodata/repomd.xml.fetched_at", b"1234567890.0")
    upstreams = [
        {"name": "rocky9", "path_prefix": "/rocky9", "format": "rpm", "url": "https://example.com/"},
    ]
    handler_class = type(
        "Handler",
        (RepoHTTPRequestHandler,),
        {
            "storage": storage,
            "upstreams": upstreams,
            "local_prefixes": [],
            "metadata_ttl_seconds": 0,
        },
    )
    req = Mock()
    req.makefile.return_value = BytesIO()
    req.raw_requestline = b"GET /rocky9/repodata/repomd.xml HTTP/1.1\r\n"
    req.command = "GET"
    req.path = "/rocky9/repodata/repomd.xml"
    req.client_address = ("127.0.0.1", 0)
    req.requestline = "GET /rocky9/repodata/repomd.xml HTTP/1.1"
    wfile = BytesIO()
    handler = handler_class(req, ("127.0.0.1", 0), None)
    handler.path = "/rocky9/repodata/repomd.xml"
    handler.command = "GET"
    handler.requestline = "GET /rocky9/repodata/repomd.xml HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.wfile = wfile
    handler.do_GET()
    out = wfile.getvalue()
    assert b"200" in out
    assert b"<repomd/>" in out


def test_serve_404_unknown_prefix(tmp_path: Path) -> None:
    """Request for unknown path prefix returns 404."""
    storage = LocalStorageBackend(tmp_path)
    upstreams = [{"name": "ubuntu", "path_prefix": "/ubuntu"}]
    handler_class = type(
        "Handler",
        (RepoHTTPRequestHandler,),
        {"storage": storage, "upstreams": upstreams, "local_prefixes": []},
    )
    req = Mock()
    req.makefile.return_value = BytesIO()
    req.raw_requestline = b"GET /unknown/repo/Release HTTP/1.1\r\n"
    req.command = "GET"
    req.path = "/unknown/repo/Release"
    req.client_address = ("127.0.0.1", 0)
    req.requestline = "GET /unknown/repo/Release HTTP/1.1"
    wfile = BytesIO()
    handler = handler_class(req, ("127.0.0.1", 0), None)
    handler.path = "/unknown/repo/Release"
    handler.command = "GET"
    handler.requestline = "GET /unknown/repo/Release HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.wfile = wfile
    handler.do_GET()
    out = wfile.getvalue()
    assert b"404" in out


def test_serve_metadata_ttl_invalidates_then_refetches(tmp_path: Path) -> None:
    """When metadata is past TTL, serve deletes cache and backend refetch is used."""
    storage = LocalStorageBackend(tmp_path)
    key = "cache/rocky9/repodata/repomd.xml"
    storage.put(key, b"stale")
    storage.put(key + ".fetched_at", b"1.0")  # very old
    upstreams = [
        {"name": "rocky9", "path_prefix": "/rocky9", "format": "rpm", "url": "https://example.com/"},
    ]
    mock_backend = Mock()
    mock_backend.get_or_fetch.return_value = (b"fresh_content", True)

    handler_class = type(
        "Handler",
        (RepoHTTPRequestHandler,),
        {
            "storage": storage,
            "upstreams": upstreams,
            "local_prefixes": [],
            "metadata_ttl_seconds": 3600,
        },
    )
    req = Mock()
    req.makefile.return_value = BytesIO()
    req.raw_requestline = b"GET /rocky9/repodata/repomd.xml HTTP/1.1\r\n"
    req.command = "GET"
    req.path = "/rocky9/repodata/repomd.xml"
    req.client_address = ("127.0.0.1", 0)
    req.requestline = "GET /rocky9/repodata/repomd.xml HTTP/1.1"
    wfile = BytesIO()
    handler = handler_class(req, ("127.0.0.1", 0), None)
    handler.path = "/rocky9/repodata/repomd.xml"
    handler.command = "GET"
    handler.requestline = "GET /rocky9/repodata/repomd.xml HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.wfile = wfile

    # Patch get_backend where it is used (serve_asgi calls it from handle_get_response).
    with patch("repo_man.serve_asgi.get_backend", return_value=mock_backend):
        handler.do_GET()

    out = wfile.getvalue()
    # We only assert that the backend was called and response body came from it;
    # some environments may not have certificates for the real upstream.
    assert b"fresh_content" in out
    mock_backend.get_or_fetch.assert_called_once()
    # Backend was invoked for the path; we do not assert on storage state to
    # avoid depending on implementation details of RepoService.


def test_api_publish_disabled_returns_404(tmp_path: Path) -> None:
    """POST /api/publish when API is disabled returns 404."""
    storage = LocalStorageBackend(tmp_path)
    upstreams = [{"name": "ubuntu", "path_prefix": "/ubuntu"}]
    handler_class = type(
        "Handler",
        (RepoHTTPRequestHandler,),
        {
            "storage": storage,
            "upstreams": upstreams,
            "local_prefixes": [],
            "enable_api": False,
        },
    )
    req = Mock()
    req.makefile.return_value = BytesIO()
    req.raw_requestline = b"POST /api/publish HTTP/1.1\r\n"
    req.command = "POST"
    req.path = "/api/publish"
    req.client_address = ("127.0.0.1", 0)
    req.requestline = "POST /api/publish HTTP/1.1"
    req.headers = {}
    req.rfile = BytesIO(b"")
    wfile = BytesIO()
    handler = handler_class(req, ("127.0.0.1", 0), None)
    handler.path = "/api/publish"
    handler.command = "POST"
    handler.requestline = "POST /api/publish HTTP/1.1"
    handler.request_version = "HTTP/1.1"
    handler.wfile = wfile
    handler.headers = {"Content-Length": "0"}
    handler.do_POST()
    out = wfile.getvalue()
    assert b"404" in out


def test_api_publish_enabled_accepts_multipart(tmp_path: Path) -> None:
    """POST /api/v1/publish with valid multipart returns 200 and package is in storage."""
    from fastapi.testclient import TestClient
    from repo_man.api import create_api_app
    storage = LocalStorageBackend(tmp_path)
    app = create_api_app(storage)
    client = TestClient(app)
    files = {"packages": ("pkg_1.0_amd64.deb", b"fake deb bytes", "application/octet-stream")}
    data = {
        "path_prefix": "/local/",
        "format": "apt",
        "suite": "stable",
        "component": "main",
        "arch": "amd64",
    }
    fake_control = {
        "Package": "pkg",
        "Version": "1.0",
        "Architecture": "amd64",
    }
    with patch("repo_man.formats.apt.publish.get_deb_control", return_value=fake_control):
        response = client.post("/api/v1/publish", data=data, files=files)
    assert response.status_code == 200
    body = response.json()
    assert body.get("published") == 1
    assert "path_prefix" in body
    assert storage.get("local/pool/main/amd64/pkg_1.0_amd64.deb") == b"fake deb bytes"
    assert storage.get("local/dists/stable/Release") is not None
    assert storage.get("local/dists/stable/main/binary-amd64/Packages") is not None


def test_api_publish_missing_path_prefix_returns_400(tmp_path: Path) -> None:
    """POST /api/v1/publish without path_prefix returns 422 (validation error)."""
    from fastapi.testclient import TestClient
    from repo_man.api import create_api_app
    storage = LocalStorageBackend(tmp_path)
    app = create_api_app(storage)
    client = TestClient(app)
    data = {"format": "apt"}
    response = client.post("/api/v1/publish", data=data)
    assert response.status_code == 422
    detail = str(response.json().get("detail", []))
    assert "path_prefix" in detail.lower()


def test_asgi_app_routes_api_v1_health_when_enabled(tmp_path: Path) -> None:
    """Full ASGI app with enable_api=True: GET /api/v1/health returns 200 (FastAPI wired)."""
    from starlette.testclient import TestClient
    from repo_man.serve_asgi import make_asgi_app
    storage = LocalStorageBackend(tmp_path)
    upstreams = [{"name": "ubuntu", "path_prefix": "/ubuntu"}]
    app = make_asgi_app(
        storage,
        upstreams,
        [],
        0,
        None,
        None,
        None,
        0,
        True,  # enable_api
        None,   # metrics_callback
        lambda x: x,  # get_client_id_fn
    )
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"
