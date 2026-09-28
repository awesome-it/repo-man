#!/usr/bin/env bash
# Run the heavy GitLab suite-split Docker matrix (focal/jammy/noble).
# Requires Docker, disk space for multiple gitlab-ce .debs, and network to packages.gitlab.com.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export RUN_GITLAB_SUITE_DOCKER=1
exec uv run pytest -m docker tests/docker/test_gitlab_suites.py -v --tb=short "$@"
