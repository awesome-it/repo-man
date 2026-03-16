"""RPM version comparison (epoch:version-release) for ordering and prune."""

from __future__ import annotations

import re


def _parse_segment(s: str) -> list[str | int]:
    """Split version segment into alternating digit/non-digit parts."""
    out: list[str | int] = []
    for m in re.finditer(r"(\d+)|([^0-9]+)", s):
        g1, g2 = m.group(1), m.group(2)
        if g1:
            out.append(int(g1))
        else:
            out.append(g2 or "")
    return out


def _cmp_part(a: str | int, b: str | int) -> int:
    """Compare one part: -1 if a < b, 0 if a == b, 1 if a > b."""
    if isinstance(a, int) and isinstance(b, int):
        return (a > b) - (a < b)
    if isinstance(a, int):
        return 1
    if isinstance(b, int):
        return -1
    sa, sb = str(a), str(b)
    return (sa > sb) - (sa < sb)


def compare_versions(a: str, b: str) -> int:
    """
    Compare RPM version-release strings (optionally with epoch).
    Format: [epoch:]version[-release]. Returns -1 if a < b, 0 if a == b, 1 if a > b.
    """
    def parse(v: str) -> tuple[int, list[str | int], list[str | int]]:
        v = v.strip()
        epoch = 0
        if ":" in v:
            ep, v = v.split(":", 1)
            try:
                epoch = int(ep.strip())
            except ValueError:
                pass
        if "-" in v:
            idx = v.rfind("-")
            version = v[:idx]
            release = v[idx + 1:]
        else:
            version = v
            release = "0"
        return epoch, _parse_segment(version), _parse_segment(release)

    ea, va, ra = parse(a)
    eb, vb, rb = parse(b)
    if ea != eb:
        return (ea > eb) - (ea < eb)
    for pa, pb in zip(va, vb):
        c = _cmp_part(pa, pb)
        if c != 0:
            return c
    if len(va) != len(vb):
        return (len(va) > len(vb)) - (len(va) < len(vb))
    for pa, pb in zip(ra, rb):
        c = _cmp_part(pa, pb)
        if c != 0:
            return c
    return (len(ra) > len(rb)) - (len(ra) < len(rb))
