"""Alpine package version comparison for ordering and prune."""

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
    Compare Alpine package versions. Format often is version-rN (e.g. 1.0.0-r0).
    Returns -1 if a < b, 0 if a == b, 1 if a > b.
    """
    def parse(v: str) -> list[str | int]:
        v = v.strip()
        # Optional -r revision suffix
        if "-r" in v and re.search(r"-r\d+$", v):
            v = v.rsplit("-r", 1)[0]
        return _parse_segment(v)

    va = parse(a)
    vb = parse(b)
    for pa, pb in zip(va, vb):
        c = _cmp_part(pa, pb)
        if c != 0:
            return c
    return (len(va) > len(vb)) - (len(va) < len(vb))
