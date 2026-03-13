"""Integration test: prune keeps latest N versions per package; disk watermark frees cache only."""

from pathlib import Path

import pytest

from repo_man.disk import get_repo_disk_usage_bytes
from repo_man.formats.apt.cache import (
    free_disk_until_under_watermark,
    list_cached_packages_by_name,
    prune_upstream,
)
from repo_man.storage.local import LocalStorageBackend


def test_prune_keeps_latest_n(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    prefix = "cache/test-upstream"
    # Simulate 4 versions of pkg-a and 2 of pkg-b
    for v in ("1.0", "1.1", "1.2", "2.0"):
        storage.put(f"{prefix}/pool/main/amd64/pkg-a_{v}_amd64.deb", b"x")
    for v in ("1.0", "1.1"):
        storage.put(f"{prefix}/pool/main/amd64/pkg-b_{v}_amd64.deb", b"y")
    removed = prune_upstream(storage, "test-upstream", keep_versions_per_package=2)
    assert removed == 2  # pkg-a: keep 2.0 and 1.2, remove 1.1 and 1.0
    by_name = list_cached_packages_by_name(storage, "test-upstream")
    assert len(by_name.get("pkg-a", [])) == 2
    assert len(by_name.get("pkg-b", [])) == 2


def test_free_disk_until_under_watermark_keeps_published(tmp_path: Path) -> None:
    """When over watermark, only cache is pruned; published (local/) is kept."""
    storage = LocalStorageBackend(tmp_path)
    # Published package (must be kept)
    storage.put("local/pool/main/amd64/important_1.0_amd64.deb", b"published-content")
    # Cached packages (may be freed)
    storage.put("cache/up/pool/main/amd64/pkg_1.0_amd64.deb", b"cached-one")
    storage.put("cache/up/pool/main/amd64/pkg_1.1_amd64.deb", b"cached-two")
    usage_before = get_repo_disk_usage_bytes(tmp_path)
    high_watermark = 20  # below current usage so we must free
    removed = free_disk_until_under_watermark(
        storage,
        ["up"],
        high_watermark,
        lambda: get_repo_disk_usage_bytes(tmp_path),
    )
    usage_after = get_repo_disk_usage_bytes(tmp_path)
    assert usage_after <= high_watermark
    assert removed >= 1
    # Published package still present
    assert storage.get("local/pool/main/amd64/important_1.0_amd64.deb") == b"published-content"
