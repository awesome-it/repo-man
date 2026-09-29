"""Shared upstream HTTP helpers: error classification and content sniffing for proxy failures."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def looks_like_html(data: bytes) -> bool:
    """True if body looks like an HTML error/block page (common HTTP proxy denial)."""
    if not data:
        return False
    sample = data[:512].lstrip().lower()
    return (
        sample.startswith(b"<!doctype html")
        or sample.startswith(b"<html")
        or b"<head>" in sample[:200]
        or b"<title>" in sample[:200]
    )


def looks_like_apt_release(data: bytes) -> bool:
    """True if body looks like an APT Release/InRelease file."""
    if not data or looks_like_html(data):
        return False
    # InRelease starts with PGP armored cleartext; Release is plain key: value
    text = data[:2048].decode("utf-8", errors="replace")
    if "-----BEGIN PGP SIGNED MESSAGE-----" in text:
        return True
    return any(
        line.startswith(("Origin:", "Suite:", "Codename:", "Date:", "Architectures:"))
        for line in text.splitlines()
    )


def looks_like_gzip(data: bytes) -> bool:
    return len(data) >= 2 and data[:2] == b"\x1f\x8b"


def looks_like_xml(data: bytes) -> bool:
    if not data or looks_like_html(data):
        return False
    sample = data.lstrip()[:200].lower()
    return sample.startswith(b"<?xml") or sample.startswith(b"<repomd") or b"<repomd" in sample


def looks_like_deb(data: bytes) -> bool:
    """Debian package ar archive starts with !<arch>\\n."""
    return len(data) >= 8 and data[:8] == b"!<arch>\n"


def looks_like_rpm(data: bytes) -> bool:
    """RPM lead magic 0xedabeedb."""
    return len(data) >= 4 and data[:4] == b"\xed\xab\xee\xdb"


def looks_like_apk(data: bytes) -> bool:
    """Alpine .apk is a gzip (or nested) archive."""
    return looks_like_gzip(data)


def classify_exception(exc: BaseException) -> str:
    """Return a clear error string for SSL / connect / timeout / other failures."""
    # Walk cause chain for nested SSL errors from httpx/httpcore
    messages: list[str] = []
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        messages.append(f"{type(cur).__name__}: {cur}")
        cur = cur.__cause__ or cur.__context__  # type: ignore[assignment]

    joined = " | ".join(messages)
    lower = joined.lower()
    if (
        "ssl" in lower
        or "certificate" in lower
        or "certifi" in lower
        or "certificate_verify_failed" in lower
        or isinstance(exc, httpx.ConnectError)
        and "ssl" in str(exc).lower()
    ):
        return f"SSL error: {exc}"
    if isinstance(exc, httpx.TimeoutException) or "timeout" in lower:
        return f"Timeout: {exc}"
    if isinstance(exc, (httpx.ConnectError, httpx.ProxyError, ConnectionError, OSError)):
        return f"Connection error: {exc}"
    return f"Request failed: {exc}"


def format_http_status_error(url: str, status_code: int, body: bytes | None = None) -> str:
    """Describe a non-200 response; note HTML bodies typical of HTTP proxy denials."""
    if body and looks_like_html(body):
        return f"HTTP {status_code} from {url} (HTML error/proxy page instead of repo content)"
    return f"HTTP {status_code} from {url}"


def format_unexpected_content_error(url: str, expected: str, body: bytes) -> str:
    if looks_like_html(body):
        return f"Unexpected content from {url}: got HTML error/proxy page instead of {expected}"
    return f"Unexpected content from {url}: expected {expected}"


def fetch_url(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    auth: tuple[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[bytes | None, str | None]:
    """
    GET url with httpx defaults (trust_env proxies, verify SSL).
    Returns (content, None) on success, or (None, error_message).
    Does not validate content type; callers must sniff.
    """
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            r = client.get(url, headers=headers, auth=auth)
            if r.status_code == 200:
                return r.content, None
            return None, format_http_status_error(url, r.status_code, r.content)
    except Exception as e:
        return None, classify_exception(e)


def resolve_upstream_auth(
    upstream_config: dict[str, Any] | None,
) -> tuple[dict[str, str] | None, tuple[str, str] | None]:
    """Delegate to APT auth helper (bearer/basic); other formats may reuse the same config shape."""
    from repo_man.formats.apt.cache import _resolve_upstream_auth

    return _resolve_upstream_auth(upstream_config)
