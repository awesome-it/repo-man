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
    assert "status" in result.output


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


def test_status_missing_file_exits_2(tmp_path: Path) -> None:
    runner = CliRunner()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "disable_default_upstreams: true\n"
        "upstreams:\n"
        "  - name: ubuntu\n"
        "    url: http://example.com/ubuntu/\n"
        "    format: apt\n"
        "    layout: classic\n"
        "    path_prefix: /ubuntu\n"
        "    suites: [noble]\n"
        "    components: [main]\n"
        "    archs: [amd64]\n"
        "    split_suites: false\n"
    )
    result = runner.invoke(
        main,
        ["--repo-root", str(tmp_path), "--config", str(cfg), "status"],
    )
    assert result.exit_code == 2
    combined = result.output + (result.stderr or "")
    assert "No status file" in combined


def test_status_last_known_json(tmp_path: Path) -> None:
    from repo_man.health import UpstreamHealthResult, save_status

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "public_base_url: https://repo.example.com\n"
        "disable_default_upstreams: true\n"
        "upstreams:\n"
        "  - name: ubuntu\n"
        "    url: http://example.com/ubuntu/\n"
        "    format: apt\n"
        "    layout: classic\n"
        "    path_prefix: /ubuntu\n"
        "    suites: [noble]\n"
        "    components: [main]\n"
        "    archs: [amd64]\n"
        "    split_suites: false\n"
    )
    save_status(
        tmp_path,
        [
            UpstreamHealthResult(
                name="ubuntu",
                path_prefix="/ubuntu",
                format="apt",
                healthy=True,
                metadata_ok=True,
                package_ok=True,
                checked_at=1.0,
                client_urls=[],
            )
        ],
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["--repo-root", str(tmp_path), "--config", str(cfg), "--output", "json", "status"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["source"] == "last-known"
    assert data["upstreams"][0]["healthy"] is True
    assert "https://repo.example.com/ubuntu" in data["upstreams"][0]["client_urls"][0]


def test_status_check_live(tmp_path: Path) -> None:
    from unittest.mock import patch

    from repo_man.health import UpstreamHealthResult

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "disable_default_upstreams: true\n"
        "upstreams:\n"
        "  - name: ubuntu\n"
        "    url: http://example.com/ubuntu/\n"
        "    format: apt\n"
        "    path_prefix: /ubuntu\n"
        "    suites: [noble]\n"
        "    components: [main]\n"
        "    archs: [amd64]\n"
        "    split_suites: false\n"
    )

    fake = UpstreamHealthResult(
        name="ubuntu",
        path_prefix="/ubuntu",
        format="apt",
        healthy=False,
        metadata_ok=False,
        package_ok=False,
        checked_at=99.0,
        error="SSL error: self signed",
        client_urls=["deb http://<mirror-host>/ubuntu noble main"],
    )

    with patch("repo_man.cli.status_cmd.run_health_checks", return_value=[fake]):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--repo-root", str(tmp_path), "--config", str(cfg), "status", "--check"],
        )
    assert result.exit_code == 1
    assert "unhealthy" in result.output
    assert "SSL error" in result.output

