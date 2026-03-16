"""Publish .rpm packages: copy into path_prefix and generate repodata via createrepo_c."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from tempfile import mkdtemp

from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)


def publish_packages(
    path_prefix: str,
    rpm_paths: list[Path],
    arch: str,
    storage: StorageBackend,
) -> bool:
    """
    Ingest .rpm files into path_prefix, generate repodata (repomd.xml, primary.xml.gz, etc.)
    using createrepo_c if available. Returns True if any change was made.
    Requires createrepo_c on PATH for metadata generation.
    """
    if not rpm_paths:
        return False
    prefix = path_prefix.strip("/") or "local"
    changed = False
    tmp = mkdtemp(prefix="repo_man_rpm_")
    try:
        # Copy RPMs into temp dir (flat or under arch)
        for p in rpm_paths:
            if not str(p).endswith(".rpm"):
                continue
            dest = Path(tmp) / p.name
            shutil.copy2(p, dest)
        rpms_in_tmp = list(Path(tmp).glob("*.rpm"))
        if not rpms_in_tmp:
            return False
        # Generate repodata with createrepo_c
        try:
            subprocess.run(
                ["createrepo_c", tmp],
                check=True,
                capture_output=True,
                timeout=300,
            )
        except FileNotFoundError:
            logger.error(
                "createrepo_c not found. Install createrepo_c to publish RPM repos (e.g. dnf install createrepo_c)."
            )
            raise RuntimeError(
                "createrepo_c is required for RPM publish. Install it (e.g. dnf install createrepo_c)."
            )
        except subprocess.CalledProcessError as e:
            logger.error("createrepo_c failed: %s", e.stderr and e.stderr.decode() or e)
            raise
        # Upload everything to storage: RPMs + repodata
        for f in Path(tmp).rglob("*"):
            if not f.is_file():
                continue
            rel = f.relative_to(tmp)
            key = f"{prefix}/{rel.as_posix()}"
            data = f.read_bytes()
            existing = storage.get(key)
            if existing != data:
                storage.put(key, data)
                changed = True
        return changed
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
