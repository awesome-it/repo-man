"""Unit tests for disk usage and watermark config."""

from pathlib import Path

import pytest

from repo_man.disk import get_repo_disk_usage_bytes
from repo_man.config import (
    DEFAULT_DISK_HIGH_WATERMARK_BYTES,
    get_disk_high_watermark_bytes,
    load_config_file,
)


def test_get_repo_disk_usage_bytes_empty(tmp_path: Path) -> None:
    assert get_repo_disk_usage_bytes(tmp_path) == 0


def test_get_repo_disk_usage_bytes_sum(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"x" * 10)
    (tmp_path / "b").write_bytes(b"y" * 20)
    (tmp_path / "sub" / "c").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sub" / "c").write_bytes(b"z" * 5)
    assert get_repo_disk_usage_bytes(tmp_path) == 35


def test_get_repo_disk_usage_bytes_nonexistent(tmp_path: Path) -> None:
    assert get_repo_disk_usage_bytes(tmp_path / "missing") == 0


def test_get_disk_high_watermark_bytes_from_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("disk:\n  high_watermark_bytes: 10737418240\n")
    assert get_disk_high_watermark_bytes(config) == 10737418240


def test_get_disk_high_watermark_bytes_not_set(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("upstreams: []\n")
    assert get_disk_high_watermark_bytes(config) == DEFAULT_DISK_HIGH_WATERMARK_BYTES


def test_get_disk_high_watermark_bytes_disabled_in_config(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("disk:\n  high_watermark_bytes: null\n")
    assert get_disk_high_watermark_bytes(config) is None


def test_get_disk_high_watermark_bytes_disabled_in_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_MIRROR_DISK_HIGH_WATERMARK_BYTES", "off")
    assert get_disk_high_watermark_bytes(None) is None


def test_get_disk_high_watermark_bytes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPO_MIRROR_DISK_HIGH_WATERMARK_BYTES", "5000000000")
    assert get_disk_high_watermark_bytes(None) == 5000000000
