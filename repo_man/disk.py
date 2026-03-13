"""Disk usage for repo root (used by disk watermark pruning)."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def get_repo_disk_usage_bytes(repo_root: Path | str) -> int:
    """Return total size in bytes of all files under repo_root. Published (e.g. local/) is included."""
    root = Path(repo_root)
    if not root.exists() or not root.is_dir():
        return 0
    total = 0
    try:
        for f in root.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError as e:
                    logger.warning("Disk usage: could not stat file=%s error=%s", f, e)
    except OSError as e:
        logger.warning("Disk usage failed: root=%s error=%s", root, e)
    return total
