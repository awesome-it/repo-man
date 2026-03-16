"""Parse and generate APT metadata (Release, Packages)."""

from __future__ import annotations

import gzip
import io
import time
from typing import Any, Iterator


def parse_release(content: bytes) -> dict[str, str]:
    """Parse Release file into key-value pairs (single-valued)."""
    out: dict[str, str] = {}
    for line in content.decode("utf-8", errors="replace").splitlines():
        if line and not line.startswith(" ") and ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def parse_packages_stanzas(content: bytes) -> Iterator[dict[str, str]]:
    """Yield control stanzas from a Packages file (or Packages.gz)."""
    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    text = content.decode("utf-8", errors="replace")
    current: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith(" "):
            if current and "Description" in current:
                current["Description"] = current.get("Description", "") + "\n" + line
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            key = k.strip()
            value = v.strip()
            if key == "Description":
                current[key] = value
            else:
                current[key] = value
        elif not line.strip() and current:
            yield current
            current = {}
    if current:
        yield current


def generate_packages(stanzas: list[dict[str, str]]) -> str:
    """Generate Packages file content from control stanzas."""
    lines: list[str] = []
    for s in stanzas:
        for k, v in s.items():
            if "\n" in v:
                lines.append(f"{k}:")
                for part in v.split("\n"):
                    lines.append(f" {part}")
            else:
                lines.append(f"{k}: {v}")
        lines.append("")
    return "\n".join(lines)


def generate_release(
    architectures: list[str],
    components: list[str],
    suite: str,
    codename: str | None = None,
    origin: str = "repo-man",
    label: str = "repo-man",
    md5_sums: dict[str, tuple[str, int]] | None = None,
    sha256_sums: dict[str, tuple[str, int]] | None = None,
) -> str:
    """Generate minimal Release file content."""
    codename = codename or suite
    # RFC 2822 date so APT accepts the Release file
    date_rfc2822 = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime())
    lines = [
        f"Origin: {origin}",
        f"Label: {label}",
        f"Suite: {suite}",
        f"Codename: {codename}",
        f"Date: {date_rfc2822}",
        f"Architectures: {' '.join(architectures)}",
        f"Components: {' '.join(components)}",
        "Description: repo-man local/cache",
    ]
    if md5_sums:
        lines.append("MD5Sum:")
        for path, (h, size) in md5_sums.items():
            lines.append(f" {h} {size} {path}")
    if sha256_sums:
        lines.append("SHA256:")
        for path, (h, size) in sha256_sums.items():
            lines.append(f" {h} {size} {path}")
    return "\n".join(lines) + "\n"
