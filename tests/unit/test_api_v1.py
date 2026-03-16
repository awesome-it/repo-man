"""Unit tests for FastAPI /api/v1 endpoints."""

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from repo_man.api import create_api_app
from repo_man.storage.local import LocalStorageBackend


def test_health_returns_ok(tmp_path: Path) -> None:
    """GET /api/v1/health returns 200 and status ok."""
    storage = LocalStorageBackend(tmp_path)
    app = create_api_app(storage)
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_publish_invalid_format_returns_400(tmp_path: Path) -> None:
    """POST /api/v1/publish with format=invalid returns 400."""
    storage = LocalStorageBackend(tmp_path)
    app = create_api_app(storage)
    client = TestClient(app)
    data = {"path_prefix": "/local/", "format": "invalid"}
    response = client.post("/api/v1/publish", data=data)
    assert response.status_code == 400
    err = response.json().get("error", response.json().get("detail", ""))
    assert "apt" in str(err).lower() or "format" in str(err).lower()


def test_publish_no_files_returns_400(tmp_path: Path) -> None:
    """POST /api/v1/publish with path_prefix and format but no files returns 400."""
    storage = LocalStorageBackend(tmp_path)
    app = create_api_app(storage)
    client = TestClient(app)
    data = {"path_prefix": "/local/", "format": "apt"}
    response = client.post("/api/v1/publish", data=data)
    assert response.status_code == 400
    err = response.json().get("error", response.json().get("detail", ""))
    assert "package" in str(err).lower() or "file" in str(err).lower()


def test_publish_success_apt(tmp_path: Path) -> None:
    """POST /api/v1/publish with valid APT multipart returns 200 and writes to storage."""
    storage = LocalStorageBackend(tmp_path)
    app = create_api_app(storage)
    client = TestClient(app)
    files = {"packages": ("pkg_1.0_amd64.deb", b"fake deb", "application/octet-stream")}
    data = {"path_prefix": "/local/", "format": "apt", "suite": "stable", "component": "main", "arch": "amd64"}
    fake_control = {"Package": "pkg", "Version": "1.0", "Architecture": "amd64"}
    with patch("repo_man.formats.apt.publish.get_deb_control", return_value=fake_control):
        response = client.post("/api/v1/publish", data=data, files=files)
    assert response.status_code == 200
    body = response.json()
    assert body["published"] == 1
    assert body["path_prefix"] == "/local/"
    assert "changed" in body


def test_legacy_api_publish_same_as_v1(tmp_path: Path) -> None:
    """POST /api/publish behaves identically to POST /api/v1/publish for valid input."""
    storage = LocalStorageBackend(tmp_path)
    app = create_api_app(storage)
    client = TestClient(app)
    files = {"packages": ("pkg_1.0_amd64.deb", b"fake deb", "application/octet-stream")}
    data = {"path_prefix": "/local/", "format": "apt", "suite": "stable", "component": "main", "arch": "amd64"}
    fake_control = {"Package": "pkg", "Version": "1.0", "Architecture": "amd64"}
    with patch("repo_man.formats.apt.publish.get_deb_control", return_value=fake_control):
        r1 = client.post("/api/v1/publish", data=data, files=files)
        r2 = client.post("/api/publish", data=data, files=files)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json() == r2.json()
