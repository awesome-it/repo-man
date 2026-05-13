"""HTTP path predicates for Ubuntu `do-release-upgrade` support (scoped HEAD, etc.)."""

from __future__ import annotations


def is_do_release_upgrade_head_path(path: str) -> bool:
    """
    Return True if this request path may use HTTP HEAD for `do-release-upgrade`.

    Only these patterns are allowed (extend when Ubuntu adds URLs):

    1. **Dist upgrader tree** — path contains ``/dist-upgrader-`` (e.g.
       ``.../dists/noble-updates/main/dist-upgrader-all/current/ReleaseAnnouncement``).
    2. **meta-release files** — last path segment is exactly ``meta-release`` or
       ``meta-release-lts`` (see docs for pointing ``/etc/update-manager/meta-release``
       at the mirror), e.g. ``/ubuntu/meta-release-lts``.

    Query strings are ignored (caller may pass path-only as in ASGI ``scope["path"]``).
    """
    if not path:
        return False
    path_only = path.split("?", 1)[0]
    if "/dist-upgrader-" in path_only:
        return True
    segments = [s for s in path_only.split("/") if s]
    if not segments:
        return False
    last = segments[-1]
    return last in ("meta-release", "meta-release-lts")
