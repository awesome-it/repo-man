"""Unit tests for classic APT suite-split upstream expansion."""

from __future__ import annotations

from pathlib import Path

import pytest

from repo_man.config import (
    expand_split_suite_upstreams,
    get_default_upstreams,
    get_effective_upstreams,
)


def test_expand_default_splits_classic_multi_suite() -> None:
    upstreams = [
        {
            "name": "GitLab",
            "url": "https://packages.example/ubuntu/",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/GitLab",
            "suites": ["focal", "jammy", "noble"],
            "components": ["main"],
        }
    ]
    expanded = expand_split_suite_upstreams(upstreams)
    assert [u["name"] for u in expanded] == ["GitLab-focal", "GitLab-jammy", "GitLab-noble"]
    assert [u["path_prefix"] for u in expanded] == ["/GitLab/focal", "/GitLab/jammy", "/GitLab/noble"]
    assert [u["suites"] for u in expanded] == [["focal"], ["jammy"], ["noble"]]
    assert all("split_suites" not in u for u in expanded)
    assert all(u["url"] == "https://packages.example/ubuntu/" for u in expanded)


def test_expand_explicit_false_keeps_single_prefix() -> None:
    upstreams = [
        {
            "name": "ubuntu",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/ubuntu",
            "suites": ["jammy", "noble"],
            "split_suites": False,
        }
    ]
    expanded = expand_split_suite_upstreams(upstreams)
    assert len(expanded) == 1
    assert expanded[0]["name"] == "ubuntu"
    assert expanded[0]["path_prefix"] == "/ubuntu"
    assert expanded[0]["suites"] == ["jammy", "noble"]


def test_expand_single_suite_no_split() -> None:
    upstreams = [
        {
            "name": "GitLab",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/GitLab",
            "suites": ["jammy"],
        }
    ]
    expanded = expand_split_suite_upstreams(upstreams)
    assert len(expanded) == 1
    assert expanded[0]["path_prefix"] == "/GitLab"


def test_expand_skips_non_classic_and_non_apt() -> None:
    upstreams = [
        {
            "name": "k8s",
            "format": "apt",
            "layout": "single-stream",
            "path_prefix": "/k8s",
            "suites": ["v1", "v2"],
        },
        {
            "name": "rocky",
            "format": "rpm",
            "path_prefix": "/rocky9",
            "suites": ["a", "b"],
        },
    ]
    expanded = expand_split_suite_upstreams(upstreams)
    assert len(expanded) == 2
    assert expanded[0]["path_prefix"] == "/k8s"
    assert expanded[1]["path_prefix"] == "/rocky9"


def test_expand_path_prefix_collision_raises() -> None:
    upstreams = [
        {
            "name": "a",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/GitLab/jammy",
            "suites": ["jammy"],
        },
        {
            "name": "GitLab",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/GitLab",
            "suites": ["jammy", "noble"],
        },
    ]
    with pytest.raises(ValueError, match="path_prefix collision"):
        expand_split_suite_upstreams(upstreams)


def test_default_upstreams_ubuntu_debian_not_split() -> None:
    defaults = get_default_upstreams()
    ubuntu = next(u for u in defaults if u["name"] == "ubuntu")
    debian = next(u for u in defaults if u["name"] == "debian")
    assert ubuntu.get("split_suites") is False
    assert debian.get("split_suites") is False
    expanded = expand_split_suite_upstreams(defaults)
    names = {u["name"] for u in expanded}
    assert "ubuntu" in names
    assert "debian" in names
    assert "ubuntu-jammy" not in names
    assert "debian-bookworm" not in names


def test_get_effective_upstreams_expands_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "upstreams:\n"
        "  - name: GitLab\n"
        "    url: https://packages.example/ubuntu/\n"
        "    format: apt\n"
        "    layout: classic\n"
        "    path_prefix: /GitLab\n"
        "    suites: [jammy, noble]\n"
    )
    upstreams, used_defaults = get_effective_upstreams(config_path)
    assert used_defaults is False
    assert [u["path_prefix"] for u in upstreams] == ["/GitLab/jammy", "/GitLab/noble"]


def test_get_effective_upstreams_defaults_remain_unsplit(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.yaml"
    upstreams, used_defaults = get_effective_upstreams(config_path)
    assert used_defaults is True
    prefixes = {u.get("path_prefix") for u in upstreams}
    assert "/ubuntu" in prefixes
    assert "/debian" in prefixes
