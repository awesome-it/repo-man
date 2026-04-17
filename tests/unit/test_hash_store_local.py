"""Unit tests for LocalPackageHashStore concurrency safety."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from repo_man.hash_store.local import LocalPackageHashStore


def test_local_hash_store_concurrent_set_and_get(tmp_path: Path) -> None:
    store = LocalPackageHashStore(tmp_path / "hash_store.db")
    upstream = "ubuntu"

    def worker(i: int) -> None:
        path = f"pool/main/p/pkg/pkg_{i}.deb"
        hash_value = f"hash-{i}"
        store.set(upstream, path, hash_value)
        assert store.get(upstream, path) == hash_value
        store.set_last_served(upstream, path, float(i))
        assert store.get_last_served(upstream, path) == float(i)

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(worker, range(200)))

    paths = set(store.list_paths(upstream))
    assert len(paths) == 200
    assert "pool/main/p/pkg/pkg_0.deb" in paths
    assert "pool/main/p/pkg/pkg_199.deb" in paths
