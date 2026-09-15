"""HTTP path predicates and helpers for Ubuntu `do-release-upgrade` support."""

from __future__ import annotations

import re

# Ubuntu APT hosts that appear in meta-release bodies (Release-File, UpgradeTool, …).
_UBUNTU_ARCHIVE_URL = re.compile(
    r"(?P<scheme>https?)://"
    r"(?P<host>"
    r"(?:[a-z0-9-]+\.)?archive\.ubuntu\.com|"
    r"security\.ubuntu\.com|"
    r"old-releases\.ubuntu\.com"
    r")"
    r"/ubuntu(?P<rest>/[^\s]*)?",
    re.IGNORECASE,
)

_META_RELEASE_NAMES = frozenset({"meta-release", "meta-release-lts"})


def is_meta_release_path(path: str) -> bool:
    """True when the last path segment is ``meta-release`` or ``meta-release-lts``."""
    if not path:
        return False
    path_only = path.split("?", 1)[0]
    segments = [s for s in path_only.split("/") if s]
    return bool(segments) and segments[-1] in _META_RELEASE_NAMES


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
    return is_meta_release_path(path_only)


def rewrite_meta_release_urls(body: bytes, public_origin: str, path_prefix: str) -> bytes:
    """
    Rewrite Ubuntu archive URLs in a meta-release body to this mirror.

    Maps ``http(s)://{archive-host}/ubuntu/...`` to ``{public_origin}{path_prefix}/...``
    so ``do-release-upgrade`` fetches Release files and UpgradeTool tarballs via repo-man.
    Leaves ``changelogs.ubuntu.com`` and other non-archive hosts unchanged.
    """
    origin = (public_origin or "").rstrip("/")
    if not origin:
        return body
    prefix = "/" + (path_prefix or "").strip("/")
    if prefix == "/":
        return body

    text = body.decode("utf-8", errors="replace")

    def _repl(match: re.Match[str]) -> str:
        rest = match.group("rest") or ""
        return f"{origin}{prefix}{rest}"

    return _UBUNTU_ARCHIVE_URL.sub(_repl, text).encode("utf-8")


def public_origin_from_headers(
    host: str | None,
    *,
    scheme: str = "http",
    forwarded_proto: str | None = None,
    forwarded_host: str | None = None,
) -> str | None:
    """Build ``scheme://host`` for URL rewriting from request / proxy headers."""
    effective_host = (forwarded_host or host or "").split(",", 1)[0].strip()
    if not effective_host:
        return None
    effective_scheme = (forwarded_proto or scheme or "http").split(",", 1)[0].strip().lower()
    if effective_scheme not in ("http", "https"):
        effective_scheme = "http"
    return f"{effective_scheme}://{effective_host}"
