"""Docker GitLab suite-split matrix: focal/jammy/noble install gitlab-ce + gitlab-runner.

Skipped unless RUN_GITLAB_SUITE_DOCKER=1 (heavy: multi-GB downloads).

Scenarios:
  1) Sequential install focal → jammy → noble on one cache
  2) Cross-suite reinstall after all suites cached
  3) Parallel install of all three clients
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

COMPOSE_FILE = Path(__file__).resolve().parent / "compose.gitlab-suites.yaml"
PROJECT = "repoman-gitlab-suites"
CLIENTS = ("gitlab-client-focal", "gitlab-client-jammy", "gitlab-client-noble")
# GitLab CE .debs are large; allow long pulls.
CLIENT_TIMEOUT = 60 * 60


def _enabled() -> bool:
    return os.environ.get("RUN_GITLAB_SUITE_DOCKER", "").strip().lower() in ("1", "true", "yes", "on")


def _docker_compose_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _compose(*args: str, env: dict[str, str] | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "-f",
        str(COMPOSE_FILE),
        "--profile",
        "client",
        *args,
    ]
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        cwd=_project_root(),
        capture_output=True,
        timeout=timeout,
        text=True,
        env=merged,
    )


pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _docker_compose_available(), reason="Docker or docker compose not available"),
    pytest.mark.skipif(not _enabled(), reason="Set RUN_GITLAB_SUITE_DOCKER=1 to run heavy GitLab suite matrix"),
]


@pytest.fixture(scope="module")
def gitlab_suite_stack() -> Path:
    assert COMPOSE_FILE.exists()
    # Fresh volume so sequential/parallel share a known starting point per module run
    _compose("down", "-v", timeout=180)
    build = _compose("build", "repo-man", timeout=600)
    assert build.returncode == 0, f"build failed:\n{build.stdout}\n{build.stderr}"
    up = _compose("up", "-d", "repo-man", timeout=300)
    assert up.returncode == 0, f"up failed:\n{up.stdout}\n{up.stderr}"
    # Wait until /metrics answers (Podman often omits "healthy" in `compose ps`).
    deadline = time.time() + 120
    while time.time() < deadline:
        probe = _compose(
            "exec",
            "-T",
            "repo-man",
            "python3",
            "-c",
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/metrics', timeout=5)",
            timeout=30,
        )
        if probe.returncode == 0:
            break
        time.sleep(2)
    else:
        logs = _compose("logs", "repo-man", timeout=60)
        pytest.fail(f"repo-man not healthy:\n{logs.stdout}\n{logs.stderr}")
    yield COMPOSE_FILE
    _compose("down", "-v", timeout=180)


def _run_client(service: str, mode: str) -> subprocess.CompletedProcess[str]:
    return _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        service,
        env={"CLIENT_MODE": mode},
        timeout=CLIENT_TIMEOUT,
    )


def test_sequential_install_then_cross_suite_reinstall(gitlab_suite_stack: Path) -> None:
    """Install each suite in order, then purge+reinstall after siblings warmed the cache."""
    for service in CLIENTS:
        proc = _run_client(service, "install")
        assert proc.returncode == 0, (
            f"{service} install failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        assert "OK suite=" in proc.stdout

    for service in CLIENTS:
        proc = _run_client(service, "reinstall")
        assert proc.returncode == 0, (
            f"{service} reinstall failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
        assert "OK suite=" in proc.stdout
        assert "mode=reinstall" in proc.stdout


def test_parallel_install(gitlab_suite_stack: Path) -> None:
    """All three suite clients succeed concurrently against the shared mirror."""
    # Ensure repo-man still up (module fixture); parallel wave on same cache is intentional.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_run_client, service, "install"): service for service in CLIENTS}
        for fut in as_completed(futures):
            service = futures[fut]
            proc = fut.result()
            assert proc.returncode == 0, (
                f"{service} parallel install failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
            assert "OK suite=" in proc.stdout

    # Spot-check distinct suite cache prefixes exist on the volume
    check = _compose(
        "exec",
        "-T",
        "repo-man",
        "sh",
        "-c",
        "ls /data/cache | tr '\\n' ' '",
        timeout=60,
    )
    assert check.returncode == 0, check.stderr
    listing = check.stdout
    for name in ("GitLab-focal", "GitLab-jammy", "GitLab-noble"):
        assert name in listing, f"missing cache prefix {name} in: {listing}"
