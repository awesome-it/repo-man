"""Unit tests for Alpine cache: prune_upstream, get_or_fetch (with mocks)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repo_man.formats.alpine.cache import get_or_fetch, prune_upstream
from repo_man.storage.local import LocalStorageBackend


def test_prune_upstream_keeps_latest_n(tmp_path: Path) -> None:
    """Prune keeps latest keep_versions_per_package versions per package."""
    storage = LocalStorageBackend(tmp_path)
    prefix = "cache/alpine-upstream"
    for v in ("1.0", "1.1", "1.2", "2.0"):
        storage.put(f"{prefix}/main/x86_64/foo-{v}.apk", b"x")
    for v in ("1.0", "1.1"):
        storage.put(f"{prefix}/main/x86_64/bar-{v}.apk", b"y")
    removed = prune_upstream(storage, "alpine-upstream", keep_versions_per_package=2)
    assert removed == 2
    assert storage.get(f"{prefix}/main/x86_64/foo-1.0.apk") is None
    assert storage.get(f"{prefix}/main/x86_64/foo-1.1.apk") is None
    assert storage.get(f"{prefix}/main/x86_64/foo-1.2.apk") == b"x"
    assert storage.get(f"{prefix}/main/x86_64/foo-2.0.apk") == b"x"


@patch("repo_man.formats.alpine.cache.httpx")
def test_get_or_fetch_metadata_from_upstream(mock_httpx: MagicMock, tmp_path: Path) -> None:
    """get_or_fetch for APKINDEX path fetches from upstream and stores."""
    storage = LocalStorageBackend(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"APKINDEX data"
    mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_response
    config = {"url": "https://example.com/alpine/v3.19/main"}
    data, from_upstream = get_or_fetch(
        "alpine-repo",
        "APKINDEX.tar.gz",
        config,
        storage,
    )
    assert data == b"APKINDEX data"
    assert from_upstream is True
    assert storage.get("cache/alpine-repo/APKINDEX.tar.gz") == b"APKINDEX data"


@patch("repo_man.formats.alpine.cache.httpx")
def test_get_or_fetch_package_from_upstream(mock_httpx: MagicMock, tmp_path: Path) -> None:
    """get_or_fetch for .apk path fetches from upstream and stores."""
    storage = LocalStorageBackend(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"apk payload"
    mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_response
    config = {"url": "https://example.com/alpine"}
    data, from_upstream = get_or_fetch(
        "alpine-repo",
        "main/x86_64/foo-1.0.apk",
        config,
        storage,
    )
    assert data == b"apk payload"
    assert from_upstream is True
    assert storage.get("cache/alpine-repo/main/x86_64/foo-1.0.apk") == b"apk payload"


def test_get_or_fetch_cache_hit(tmp_path: Path) -> None:
    """get_or_fetch returns cached data and from_upstream=False."""
    storage = LocalStorageBackend(tmp_path)
    storage.put("cache/my-alpine/APKINDEX.tar.gz", b"cached")
    config = {"url": "https://example.com"}
    data, from_upstream = get_or_fetch(
        "my-alpine",
        "APKINDEX.tar.gz",
        config,
        storage,
    )
    assert data == b"cached"
    assert from_upstream is False
