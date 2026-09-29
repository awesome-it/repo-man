"""Unit tests for upstream HTTP error classification and content sniffing."""

from __future__ import annotations

import httpx

from repo_man.upstream_http import (
    classify_exception,
    format_http_status_error,
    format_unexpected_content_error,
    looks_like_apt_release,
    looks_like_deb,
    looks_like_html,
    looks_like_rpm,
)


def test_looks_like_html() -> None:
    assert looks_like_html(b"<!DOCTYPE html><html><body>denied</body></html>")
    assert looks_like_html(b"<html><head><title>Error</title></head></html>")
    assert not looks_like_html(b"Origin: Ubuntu\nSuite: noble\n")


def test_looks_like_apt_release() -> None:
    assert looks_like_apt_release(b"Origin: Ubuntu\nSuite: noble\nCodename: noble\n")
    assert looks_like_apt_release(b"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\nOrigin: Ubuntu\n")
    assert not looks_like_apt_release(b"<!DOCTYPE html><html></html>")


def test_looks_like_deb_and_rpm() -> None:
    assert looks_like_deb(b"!<arch>\n...")
    assert not looks_like_deb(b"PK\x03\x04")
    assert looks_like_rpm(b"\xed\xab\xee\xdb" + b"\x00" * 10)
    assert not looks_like_rpm(b"!<arch>\n")


def test_format_http_status_html_body() -> None:
    msg = format_http_status_error(
        "http://example.com/foo",
        403,
        b"<html><body>blocked</body></html>",
    )
    assert "403" in msg
    assert "HTML" in msg or "proxy" in msg


def test_format_unexpected_html() -> None:
    msg = format_unexpected_content_error(
        "http://example.com/Release",
        "APT Release",
        b"<!DOCTYPE html><html></html>",
    )
    assert "HTML" in msg


def test_classify_ssl_like_error() -> None:
    exc = httpx.ConnectError("CERTIFICATE_VERIFY_FAILED: self signed certificate")
    msg = classify_exception(exc)
    assert "SSL" in msg or "ssl" in msg.lower() or "CERTIFICATE" in msg


def test_classify_timeout() -> None:
    exc = httpx.ReadTimeout("timed out")
    msg = classify_exception(exc)
    assert "Timeout" in msg or "timeout" in msg.lower()
