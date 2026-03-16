"""Docker-based client tests: run compose clients and assert success. Skip if Docker unavailable."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
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


@pytest.mark.skipif(not _docker_compose_available(), reason="Docker or docker compose not available")
@pytest.mark.docker
def test_api_health(compose_project_dir: Path) -> None:
    """GET /api/v1/health returns 200 and status ok (FastAPI app is wired)."""
    compose_file = compose_project_dir / "compose.integration.yaml"
    assert compose_file.exists()
    # Build and recreate repo-man so /api/v1 (FastAPI) is available
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "build", "repo-man"],
        cwd=_project_root(),
        capture_output=True,
        timeout=300,
    )
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "--force-recreate", "repo-man"],
        cwd=_project_root(),
        capture_output=True,
        timeout=60,
    )
    time.sleep(12)  # allow repo-man healthcheck to pass after recreate
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "api-health-check",
        ],
        cwd=_project_root(),
        capture_output=True,
        timeout=60,
        text=True,
    )
    assert proc.returncode == 0, (
        f"api-health-check failed (exit {proc.returncode}). stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "OK" in proc.stdout


@pytest.mark.skipif(
    not _docker_compose_available(),
    reason="Docker or docker compose not available",
)
@pytest.mark.skipif(
    os.environ.get("REPO_MIRROR_DOCKER_FRESH_BUILD") != "1",
    reason="Set REPO_MIRROR_DOCKER_FRESH_BUILD=1 to run (requires fresh repo-man image with /api/v1)",
)
@pytest.mark.docker
def test_build_publish_install(compose_project_dir: Path) -> None:
    """Build a trivial .deb, publish to repo-man via API, install from repo-man (build → publish → install)."""
    compose_file = compose_project_dir / "compose.integration.yaml"
    assert compose_file.exists(), f"compose file missing: {compose_file}"
    root = _project_root()
    # Rebuild repo-man (no cache) so image has /api/v1; down then up so the new container uses that image
    build_result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "build", "--no-cache", "repo-man"],
        cwd=root,
        capture_output=True,
        timeout=600,
        text=True,
    )
    assert build_result.returncode == 0, (
        f"repo-man build failed. stdout:\n{build_result.stdout}\nstderr:\n{build_result.stderr}"
    )
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "stop", "--timeout", "5", "repo-man"],
        cwd=root,
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "rm", "-f", "repo-man"],
        cwd=root,
        capture_output=True,
        timeout=30,
    )
    up_result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "repo-man"],
        cwd=root,
        capture_output=True,
        timeout=60,
        text=True,
    )
    assert up_result.returncode == 0, (
        f"repo-man up failed. stderr:\n{up_result.stderr}"
    )
    time.sleep(20)  # allow repo-man to become healthy and serve /api/v1
    # Run builder first (publish .deb to repo-man); then run client (install from repo-man)
    proc_builder = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "build-publish-install-builder",
        ],
        cwd=root,
        capture_output=True,
        timeout=120,
        text=True,
    )
    assert proc_builder.returncode == 0, (
        f"build-publish-install-builder failed (exit {proc_builder.returncode}). stderr:\n{proc_builder.stderr}"
    )
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "run",
            "--rm",
            "build-publish-install-client",
        ],
        cwd=root,
        capture_output=True,
        timeout=600,
        text=True,
    )
    assert proc.returncode == 0, (
        f"build-publish-install-client failed (exit {proc.returncode}). stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "hello-repoman" in proc.stdout
    assert "Build-publish-install OK" in proc.stdout
