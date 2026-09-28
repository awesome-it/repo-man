"""Unit tests for APT Packages-refresh hash store updates."""

from __future__ import annotations

import hashlib
from pathlib import Path

from repo_man.formats.apt.cache import verify_and_update_package_hashes
from repo_man.hash_store.local import LocalPackageHashStore
from repo_man.storage.local import LocalStorageBackend


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_verify_drops_blob_when_hash_changes(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    hash_store = LocalPackageHashStore(tmp_path / "hashes.db")
    path = "pool/main/g/gitlab-ce/gitlab-ce_16_amd64.deb"
    old_blob = b"old-blob"
    storage.put(f"cache/GitLab/{path}", old_blob)
    hash_store.set("GitLab", path, _sha256(old_blob))

    new_hash = _sha256(b"new-blob")
    verify_and_update_package_hashes("GitLab", {path: new_hash}, storage, hash_store)

    assert storage.get(f"cache/GitLab/{path}") is None
    assert hash_store.get("GitLab", path) == new_hash


def test_verify_removes_paths_absent_from_packages(tmp_path: Path) -> None:
    """With one suite per upstream, paths no longer in Packages are dropped."""
    storage = LocalStorageBackend(tmp_path)
    hash_store = LocalPackageHashStore(tmp_path / "hashes.db")
    keep = "pool/main/a/apt/apt_1_amd64.deb"
    gone = "pool/main/g/gone/gone_1_amd64.deb"
    storage.put(f"cache/u/{keep}", b"keep")
    storage.put(f"cache/u/{gone}", b"gone")
    hash_store.set("u", keep, _sha256(b"keep"))
    hash_store.set("u", gone, _sha256(b"gone"))

    verify_and_update_package_hashes("u", {keep: _sha256(b"keep")}, storage, hash_store)

    assert storage.get(f"cache/u/{keep}") == b"keep"
    assert storage.get(f"cache/u/{gone}") is None
    assert hash_store.get("u", gone) is None
