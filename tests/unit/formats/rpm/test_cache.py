"""Unit tests for RPM cache: prune_upstream, get_or_fetch (with mocks)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from repo_man.formats.rpm.cache import get_or_fetch, prune_upstream
from repo_man.storage.local import LocalStorageBackend


def test_prune_upstream_keeps_latest_n(tmp_path: Path) -> None:
    """Prune keeps latest keep_versions_per_package versions per package."""
    storage = LocalStorageBackend(tmp_path)
    prefix = "cache/rpm-upstream"
    # foo: 1.0, 1.1, 1.2, 2.0; bar: 1.0, 1.1
    for v in ("1.0", "1.1", "1.2", "2.0"):
        storage.put(f"{prefix}/Packages/f/foo-{v}-1.x86_64.rpm", b"x")
    for v in ("1.0", "1.1"):
        storage.put(f"{prefix}/Packages/b/bar-{v}-1.noarch.rpm", b"y")
    removed = prune_upstream(storage, "rpm-upstream", keep_versions_per_package=2)
    assert removed == 2  # foo: keep 2.0 and 1.2; bar: keep both
    # Check foo: 1.0 and 1.1 removed
    assert storage.get(f"{prefix}/Packages/f/foo-1.0-1.x86_64.rpm") is None
    assert storage.get(f"{prefix}/Packages/f/foo-1.1-1.x86_64.rpm") is None
    assert storage.get(f"{prefix}/Packages/f/foo-1.2-1.x86_64.rpm") == b"x"
    assert storage.get(f"{prefix}/Packages/f/foo-2.0-1.x86_64.rpm") == b"x"


@patch("repo_man.formats.rpm.cache.httpx")
def test_get_or_fetch_metadata_from_upstream(mock_httpx: MagicMock, tmp_path: Path) -> None:
    """get_or_fetch for repodata path fetches from upstream and stores."""
    storage = LocalStorageBackend(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"<repomd/>"
    mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_response
    config = {"url": "https://example.com/repo"}
    data, from_upstream = get_or_fetch(
        "rpm-repo",
        "repodata/repomd.xml",
        config,
        storage,
    )
    assert data == b"<repomd/>"
    assert from_upstream is True
    assert storage.get("cache/rpm-repo/repodata/repomd.xml") == b"<repomd/>"
    assert storage.get("cache/rpm-repo/repodata/repomd.xml.fetched_at") is not None


@patch("repo_man.formats.rpm.cache.httpx")
def test_get_or_fetch_package_from_upstream(mock_httpx: MagicMock, tmp_path: Path) -> None:
    """get_or_fetch for .rpm path fetches from upstream and stores."""
    storage = LocalStorageBackend(tmp_path)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"rpm payload"
    mock_httpx.Client.return_value.__enter__.return_value.get.return_value = mock_response
    config = {"url": "https://example.com/repo"}
    data, from_upstream = get_or_fetch(
        "rpm-repo",
        "Packages/f/foo-1.0-1.x86_64.rpm",
        config,
        storage,
    )
    assert data == b"rpm payload"
    assert from_upstream is True
    assert storage.get("cache/rpm-repo/Packages/f/foo-1.0-1.x86_64.rpm") == b"rpm payload"


def test_get_or_fetch_cache_hit(tmp_path: Path) -> None:
    """get_or_fetch returns cached data and from_upstream=False."""
    storage = LocalStorageBackend(tmp_path)
    storage.put("cache/my-repo/repodata/repomd.xml", b"cached")
    config = {"url": "https://example.com"}
    data, from_upstream = get_or_fetch(
        "my-repo",
        "repodata/repomd.xml",
        config,
        storage,
    )
    assert data == b"cached"
    assert from_upstream is False
