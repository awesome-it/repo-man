"""Docker-based client tests: run compose clients and assert success. Skip if Docker unavailable."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _docker_compose_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


@pytest.fixture(scope="module")
def compose_project_dir() -> Path:
    """Directory containing compose.integration.yaml."""
    return Path(__file__).resolve().parent


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


@pytest.mark.skipif(not _docker_compose_available(), reason="Docker or docker compose not available")
@pytest.mark.docker
def test_rpm_client_installs_package(compose_project_dir: Path) -> None:
    """Run rpm-client service: dnf install tar via repo-man mirror. Fails if Rocky/mirror path is broken."""
    compose_file = compose_project_dir / "compose.integration.yaml"
    assert compose_file.exists(), f"compose file missing: {compose_file}"
    # Ensure repo-man is up (compose run will start dependencies)
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "rpm-client",
        ],
        cwd=_project_root(),
        capture_output=True,
        timeout=300,
        text=True,
    )
    assert proc.returncode == 0, (
        f"rpm-client failed (exit {proc.returncode}). stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "Complete!" in proc.stdout or "tar" in proc.stdout.lower()


@pytest.mark.skipif(not _docker_compose_available(), reason="Docker or docker compose not available")
@pytest.mark.docker
def test_alpine_client_installs_package(compose_project_dir: Path) -> None:
    """Run alpine-client: apk add musl via repo-man mirror."""
    compose_file = compose_project_dir / "compose.integration.yaml"
    assert compose_file.exists()
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "alpine-client",
        ],
        cwd=_project_root(),
        capture_output=True,
        timeout=180,
        text=True,
    )
    assert proc.returncode == 0, (
        f"alpine-client failed (exit {proc.returncode}). stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
