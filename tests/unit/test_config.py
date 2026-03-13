"""Unit tests for config."""

import os
from pathlib import Path

import pytest

from repo_man.config import (
    DEFAULT_CACHE_VERSIONS_PER_PACKAGE,
    get_cache_versions_per_package,
    get_config_path,
    get_effective_config,
    get_repo_root,
    load_config_file,
)


def test_get_repo_root_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPO_MIRROR_REPO_ROOT", raising=False)
    root = get_repo_root()
    assert "repo_data" in str(root)


def test_get_repo_root_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_MIRROR_REPO_ROOT", "/var/repo")
    assert get_repo_root() == Path("/var/repo")


def test_get_repo_root_override() -> None:
    assert get_repo_root(override=Path("/custom")) == Path("/custom")


def test_get_cache_versions_per_package_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CACHE_VERSIONS_PER_PACKAGE", raising=False)
    assert get_cache_versions_per_package() == DEFAULT_CACHE_VERSIONS_PER_PACKAGE


def test_get_cache_versions_per_package_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CACHE_VERSIONS_PER_PACKAGE", "5")
    assert get_cache_versions_per_package() == 5


def test_get_effective_config() -> None:
    cfg = get_effective_config()
    assert "repo_root" in cfg
    assert "cache_versions_per_package" in cfg
    assert "upstreams" in cfg
    assert isinstance(cfg["upstreams"], list)


def test_load_config_file_missing(tmp_path: Path) -> None:
    assert load_config_file(tmp_path / "nonexistent.yaml") == {}
