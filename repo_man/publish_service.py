"""Shared publish service: validation and format dispatch for package publishing.

Used by the FastAPI /api/v1/publish and legacy /api/publish endpoints so logic
is not duplicated.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repo_man.storage.base import StorageBackend


@dataclass(frozen=True)
class PublishResult:
    """Result of a publish operation."""

    published: int
    path_prefix: str
    changed: bool


def publish_packages(
    storage: StorageBackend,
    path_prefix: str,
    format_name: str,
    *,
    suite: str = "stable",
    component: str = "main",
    arch: str = "amd64",
    branch: str = "main",
    uploads: list[tuple[Path, bytes]],
) -> PublishResult:
    """
    Publish package files into a repo under the given path prefix.

    Validates format_name (apt, rpm, alpine) and delegates to the format backend.
    Returns PublishResult with published count, path_prefix, and whether metadata changed.
    """
    path_prefix = (path_prefix or "").strip()
    if not path_prefix:
        raise ValueError("path_prefix is required")
    format_name = (format_name or "apt").strip().lower()
    if format_name not in ("apt", "rpm", "alpine"):
        raise ValueError(f"format must be apt, rpm, or alpine; got {format_name!r}")
    if not uploads:
        raise ValueError("No package files provided")

    paths_only = [p for p, _ in uploads]
    if format_name == "apt":
        from repo_man.formats.apt.publish import publish_packages as apt_publish
        changed = apt_publish(path_prefix, paths_only, suite, component, arch, storage)
    elif format_name == "rpm":
        from repo_man.formats.rpm.publish import publish_packages as rpm_publish
        changed = rpm_publish(path_prefix, paths_only, arch, storage)
    else:
        from repo_man.formats.alpine.publish import publish_packages as alpine_publish
        changed = alpine_publish(path_prefix, paths_only, branch, storage)

    return PublishResult(published=len(uploads), path_prefix=path_prefix, changed=changed)
