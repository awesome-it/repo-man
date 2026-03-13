"""Extract control info from .deb for Packages stanza."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_deb_control(path: Path) -> dict[str, str] | None:
    """
    Extract control fields from .deb. Uses dpkg-deb -f if available, else None.
    Returns dict of field -> value for Package, Version, Architecture, etc.
    """
    try:
        r = subprocess.run(
            ["dpkg-deb", "-f", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            logger.warning("deb control extraction failed: path=%s returncode=%s stderr=%s", path, r.returncode, r.stderr)
            return None
        out: dict[str, str] = {}
        for line in r.stdout.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip()
        return out if out else None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning("deb control extraction failed: path=%s error=%s", path, e)
        return None


def control_to_packages_stanza(control: dict[str, str], filename: str) -> dict[str, str]:
    """Build a Packages-file stanza from control dict; add Filename."""
    stanza = dict(control)
    stanza["Filename"] = filename
    return stanza
