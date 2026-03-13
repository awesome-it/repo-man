"""Smoke test: CLI and config load."""

import subprocess
import sys


def test_cli_help() -> None:
    """CLI runs and shows help."""
    r = subprocess.run(
        [sys.executable, "-m", "repo_man", "--help"],
        capture_output=True,
        text=True,
        cwd=None,
    )
    assert r.returncode == 0
    assert "serve" in r.stdout
    assert "cache" in r.stdout
    assert "publish" in r.stdout
    assert "config" in r.stdout


def test_config_show() -> None:
    """config show runs."""
    r = subprocess.run(
        [sys.executable, "-m", "repo_man", "config", "show"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "repo_root" in r.stdout or "Effective config" in r.stdout
