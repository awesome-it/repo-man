"""Publish .apk packages: copy into path_prefix and generate APKINDEX.tar.gz via apk index."""

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
    apk_paths: list[Path],
    branch: str,
    storage: StorageBackend,
) -> bool:
    """
    Ingest .apk files into path_prefix, generate APKINDEX.tar.gz using `apk index`
    (requires apk-tools; typically available on Alpine). Returns True if any change was made.
    """
    if not apk_paths:
        return False
    prefix = path_prefix.strip("/") or "local"
    changed = False
    tmp = mkdtemp(prefix="repo_man_alpine_")
    try:
        for p in apk_paths:
            if not str(p).endswith(".apk"):
                continue
            dest = Path(tmp) / p.name
            shutil.copy2(p, dest)
        apks_in_tmp = list(Path(tmp).glob("*.apk"))
        if not apks_in_tmp:
            return False
        try:
            subprocess.run(
                ["apk", "index", "-o", "APKINDEX.tar.gz"] + [str(f) for f in apks_in_tmp],
                cwd=tmp,
                check=True,
                capture_output=True,
                timeout=120,
            )
        except FileNotFoundError:
            logger.error(
                "apk not found. Alpine publish requires apk-tools (e.g. on Alpine: apk add apk-tools)."
            )
            raise RuntimeError(
                "apk is required for Alpine publish. Install apk-tools (e.g. on Alpine: apk add apk-tools)."
            )
        except subprocess.CalledProcessError as e:
            logger.error("apk index failed: %s", e.stderr and e.stderr.decode() or e)
            raise
        # Upload APKINDEX and .apk files to storage (optionally under branch/arch)
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
