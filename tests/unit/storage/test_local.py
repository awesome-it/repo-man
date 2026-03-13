"""Unit tests for local storage backend."""

from pathlib import Path

import pytest

from repo_man.storage.local import LocalStorageBackend


def test_put_get(local_storage: LocalStorageBackend) -> None:
    local_storage.put("ns/key", b"hello")
    assert local_storage.get("ns/key") == b"hello"


def test_get_missing(local_storage: LocalStorageBackend) -> None:
    assert local_storage.get("nonexistent") is None


def test_exists(local_storage: LocalStorageBackend) -> None:
    assert local_storage.exists("a") is False
    local_storage.put("a", b"x")
    assert local_storage.exists("a") is True


def test_list_prefix(local_storage: LocalStorageBackend) -> None:
    local_storage.put("upstream/ubuntu/Release", b"")
    local_storage.put("upstream/ubuntu/pool/main/Packages", b"")
    local_storage.put("upstream/debian/Release", b"")
    keys = sorted(local_storage.list_prefix("upstream/ubuntu"))
    assert keys == ["upstream/ubuntu/Release", "upstream/ubuntu/pool/main/Packages"]


def test_delete_file(local_storage: LocalStorageBackend) -> None:
    local_storage.put("f", b"x")
    assert local_storage.delete("f") is True
    assert local_storage.get("f") is None
    assert local_storage.delete("f") is False


def test_namespacing(local_storage: LocalStorageBackend) -> None:
    local_storage.put("upstream/ubuntu/Release", b"u")
    local_storage.put("upstream/crio/Release", b"c")
    assert local_storage.get("upstream/ubuntu/Release") == b"u"
    assert local_storage.get("upstream/crio/Release") == b"c"
