"""Unit tests for APT upstream auth resolution."""

from __future__ import annotations

from typing import Any

from repo_man.formats.apt import cache as apt_cache


class _DummyResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"ok") -> None:
        self.status_code = status_code
        self.content = content


def test_fetch_metadata_uses_bearer_auth_from_env(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, **_: Any) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None, auth: Any = None) -> _DummyResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["auth"] = auth
            return _DummyResponse()

    monkeypatch.setenv("REPO_MIRROR_ESM_TOKEN", "secret-token")
    monkeypatch.setattr(apt_cache.httpx, "Client", _Client)

    data = apt_cache.fetch_metadata_from_upstream(
        "https://esm.ubuntu.com/infra/ubuntu/",
        "dists/jammy-infra-security/Release",
        {
            "auth": {
                "type": "bearer",
                "token_env": "REPO_MIRROR_ESM_TOKEN",
            }
        },
    )

    assert data == b"ok"
    assert captured["url"] == "https://esm.ubuntu.com/infra/ubuntu/dists/jammy-infra-security/Release"
    assert captured["headers"] == {"Authorization": "Bearer secret-token"}
    assert captured["auth"] is None


def test_fetch_metadata_uses_basic_auth_from_env(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, **_: Any) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None, auth: Any = None) -> _DummyResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["auth"] = auth
            return _DummyResponse()

    monkeypatch.setenv("REPO_MIRROR_ESM_USER", "esm-user")
    monkeypatch.setenv("REPO_MIRROR_ESM_PASS", "esm-pass")
    monkeypatch.setattr(apt_cache.httpx, "Client", _Client)

    data = apt_cache.fetch_metadata_from_upstream(
        "https://esm.ubuntu.com/infra/ubuntu/",
        "dists/jammy-infra-security/Release",
        {
            "auth": {
                "type": "basic",
                "username_env": "REPO_MIRROR_ESM_USER",
                "password_env": "REPO_MIRROR_ESM_PASS",
            }
        },
    )

    assert data == b"ok"
    assert captured["url"] == "https://esm.ubuntu.com/infra/ubuntu/dists/jammy-infra-security/Release"
    assert captured["headers"] is None
    assert captured["auth"] == ("esm-user", "esm-pass")


def test_fetch_metadata_uses_bearer_auth_from_config_token(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, **_: Any) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None, auth: Any = None) -> _DummyResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["auth"] = auth
            return _DummyResponse()

    monkeypatch.setattr(apt_cache.httpx, "Client", _Client)

    data = apt_cache.fetch_metadata_from_upstream(
        "https://esm.ubuntu.com/infra/ubuntu/",
        "dists/jammy-infra-security/Release",
        {
            "auth": {
                "type": "bearer",
                "token": "config-token",
            }
        },
    )

    assert data == b"ok"
    assert captured["url"] == "https://esm.ubuntu.com/infra/ubuntu/dists/jammy-infra-security/Release"
    assert captured["headers"] == {"Authorization": "Bearer config-token"}
    assert captured["auth"] is None


def test_fetch_metadata_without_auth_when_token_missing(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    class _Client:
        def __init__(self, **_: Any) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
            return None

        def get(self, url: str, headers: dict[str, str] | None = None, auth: Any = None) -> _DummyResponse:
            captured["url"] = url
            captured["headers"] = headers
            captured["auth"] = auth
            return _DummyResponse()

    monkeypatch.delenv("REPO_MIRROR_ESM_TOKEN", raising=False)
    monkeypatch.setattr(apt_cache.httpx, "Client", _Client)

    data = apt_cache.fetch_metadata_from_upstream(
        "https://esm.ubuntu.com/infra/ubuntu/",
        "dists/jammy-infra-security/Release",
        {
            "auth": {
                "type": "bearer",
                "token_env": "REPO_MIRROR_ESM_TOKEN",
            }
        },
    )

    assert data == b"ok"
    assert captured["headers"] is None
    assert captured["auth"] is None
