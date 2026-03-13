"""Debian version comparison for ordering (prune keeps latest N)."""

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
        return 1  # digits after non-digits
    if isinstance(b, int):
        return -1
    sa, sb = str(a), str(b)
    if sa == "~" and sb != "~":
        return -1
    if sa != "~" and sb == "~":
        return 1
    if sa < sb:
        return -1
    if sa > sb:
        return 1
    return 0


def compare_versions(a: str, b: str) -> int:
    """
    Compare Debian versions. Returns -1 if a < b, 0 if a == b, 1 if a > b.
    Simplified but handles epoch:upstream-revision and ~ for pre-releases.
    """
    def split_version(v: str) -> tuple[int, str, str]:
        epoch = 0
        rest = v.strip()
        if ":" in rest:
            ep, rest = rest.split(":", 1)
            try:
                epoch = int(ep.strip())
            except ValueError:
                pass
        if "-" in rest and rest.count("-") >= 1:
            # last hyphen separates debian revision
            idx = rest.rfind("-")
            upstream = rest[:idx]
            revision = rest[idx + 1:]
        else:
            upstream = rest
            revision = "0"
        return epoch, upstream, revision

    ea, ua, ra = split_version(a)
    eb, ub, rb = split_version(b)
    if ea != eb:
        return (ea > eb) - (ea < eb)
    for pa, pb in zip(_parse_segment(ua), _parse_segment(ub)):
        c = _cmp_part(pa, pb)
        if c != 0:
            return c
    if len(_parse_segment(ua)) != len(_parse_segment(ub)):
        return (len(_parse_segment(ua)) > len(_parse_segment(ub))) - (len(_parse_segment(ua)) < len(_parse_segment(ub)))
    for pa, pb in zip(_parse_segment(ra), _parse_segment(rb)):
        c = _cmp_part(pa, pb)
        if c != 0:
            return c
    return (len(_parse_segment(ra)) > len(_parse_segment(rb))) - (len(_parse_segment(ra)) < len(_parse_segment(rb)))
