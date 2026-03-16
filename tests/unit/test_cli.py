"""CLI-level tests using Click's CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from repo_man.cli.main import main


def test_main_help() -> None:
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    # Basic structure and subcommands should be present
    assert "Usage:" in result.output
    assert "cache" in result.output
    assert "serve" in result.output
    assert "publish" in result.output
    assert "config" in result.output


def test_config_show_uses_effective_defaults(tmp_path: Path) -> None:
    """config show without a config file should still work and list upstreams (defaults)."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--repo-root", str(tmp_path), "config", "show"],
    )
    assert result.exit_code == 0
    out = result.output
    assert "Effective config:" in out
    assert "upstreams:" in out


def test_config_show_json(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--repo-root", str(tmp_path), "--output", "json", "config", "show"],
    )
    assert result.exit_code == 0
    cfg = json.loads(result.output)
    assert "repo_root" in cfg
    assert "upstreams" in cfg
    assert isinstance(cfg["upstreams"], list)


def test_cache_add_upstream_check_mode(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "cache",
            "add-upstream",
            "--name",
            "ubuntu",
            "--url",
            "https://archive.ubuntu.com/ubuntu/",
            "--format",
            "apt",
        ],
    )
    # The top-level main wrapper swallows INFO logs by default; just assert success.
    assert result.exit_code == 0


def test_publish_add_no_files_errors(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--repo-root",
            str(tmp_path),
            "publish",
            "add",
            "--path-prefix",
            "/local/",
        ],
    )
    assert result.exit_code != 0
    assert "No package files given." in result.output

