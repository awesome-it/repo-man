"""Unit tests for config."""

import os
from pathlib import Path

import pytest

from repo_man.config import (
    DEFAULT_CACHE_VERSIONS_PER_PACKAGE,
    get_cache_versions_per_package,
    get_config_path,
    get_default_upstreams,
    get_disable_default_upstreams,
    get_effective_config,
    get_effective_upstreams,
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


def test_get_default_upstreams() -> None:
    defaults = get_default_upstreams()
    assert isinstance(defaults, list)
    assert len(defaults) >= 4
    names = {u.get("name") for u in defaults}
    assert "ubuntu" in names
    assert "debian" in names
    assert "rocky9" in names
    assert "alpine" in names
    prefixes = {u.get("path_prefix") for u in defaults}
    assert "/ubuntu" in prefixes
    assert "/debian" in prefixes


def test_get_effective_upstreams_no_config_uses_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    assert not config_path.exists()
    upstreams, used_defaults = get_effective_upstreams(config_path, no_default_upstreams_flag=False)
    assert used_defaults is True
    assert len(upstreams) >= 4


def test_get_effective_upstreams_no_defaults_flag(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    upstreams, used_defaults = get_effective_upstreams(config_path, no_default_upstreams_flag=True)
    assert used_defaults is False
    assert upstreams == []


def test_get_effective_upstreams_config_with_upstreams(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("upstreams:\n  - name: custom\n    url: https://example.com/\n    path_prefix: /custom\n")
    upstreams, used_defaults = get_effective_upstreams(config_path, no_default_upstreams_flag=False)
    assert used_defaults is False
    assert len(upstreams) == 1
    assert upstreams[0]["name"] == "custom"


def test_get_disable_default_upstreams_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_MIRROR_NO_DEFAULT_UPSTREAMS", "1")
    assert get_disable_default_upstreams(None, flag_override=None) is True
    monkeypatch.setenv("REPO_MIRROR_NO_DEFAULT_UPSTREAMS", "true")
    assert get_disable_default_upstreams(None, flag_override=None) is True
    monkeypatch.delenv("REPO_MIRROR_NO_DEFAULT_UPSTREAMS", raising=False)
    assert get_disable_default_upstreams(None, flag_override=None) is False


def test_get_disable_default_upstreams_config_key(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("disable_default_upstreams: true\n")
    assert get_disable_default_upstreams(config_path, flag_override=None) is True
    config_path.write_text("disable_default_upstreams: false\nupstreams: []\n")
    assert get_disable_default_upstreams(config_path, flag_override=None) is False
