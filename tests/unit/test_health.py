"""Unit tests for upstream health probes, status store, client URLs, metrics."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path
from unittest.mock import patch

from repo_man.health import (
    PLACEHOLDER_BASE,
    UpstreamHealthResult,
    apply_health_metrics,
    build_client_urls,
    load_status,
    probe_upstream,
    save_status,
)
from repo_man.metrics import get_metrics_output


def test_build_client_urls_apt_with_public_base() -> None:
    urls = build_client_urls(
        {
            "name": "ubuntu",
            "format": "apt",
            "layout": "classic",
            "path_prefix": "/ubuntu",
            "suites": ["noble"],
            "components": ["main", "universe"],
        },
        "https://repo.example.com",
    )
    assert urls == ["deb https://repo.example.com/ubuntu noble main universe"]


def test_build_client_urls_placeholder() -> None:
    urls = build_client_urls(
        {"name": "rocky9", "format": "rpm", "path_prefix": "/rocky9"},
        None,
    )
    assert urls == [f"baseurl={PLACEHOLDER_BASE}/rocky9"]


def test_build_client_urls_alpine() -> None:
    urls = build_client_urls(
        {"name": "alpine", "format": "alpine", "path_prefix": "/alpine"},
        "http://mirror:8080",
    )
    assert urls == ["http://mirror:8080/alpine"]


def test_status_json_round_trip(tmp_path: Path) -> None:
    results = [
        UpstreamHealthResult(
            name="ubuntu",
            path_prefix="/ubuntu",
            format="apt",
            healthy=True,
            metadata_ok=True,
            package_ok=True,
            checked_at=123.0,
            client_urls=["deb http://x/ubuntu noble main"],
        )
    ]
    path = save_status(tmp_path, results)
    assert path.exists()
    loaded = load_status(tmp_path)
    assert loaded is not None
    assert loaded["upstreams"][0]["name"] == "ubuntu"
    assert loaded["upstreams"][0]["healthy"] is True
    r = UpstreamHealthResult.from_dict(loaded["upstreams"][0])
    assert r.healthy and r.name == "ubuntu"


def _fake_fetch(url: str, **kwargs):
    """Route fake upstream responses for APT classic probe."""
    if url.endswith("/dists/noble/InRelease") or url.endswith("/dists/noble/Release"):
        return b"Origin: Ubuntu\nSuite: noble\nCodename: noble\n", None
    if "Packages.gz" in url:
        body = (
            "Package: tiny\n"
            "Filename: pool/main/t/tiny/tiny_1_amd64.deb\n"
            "Size: 64\n"
            "\n"
            "Package: huge\n"
            "Filename: pool/main/h/huge/huge_1_amd64.deb\n"
            "Size: 99999999\n"
            "\n"
        ).encode()
        return gzip.compress(body), None
    if url.endswith(".deb"):
        return b"!<arch>\n" + b"x" * 20, None
    return None, f"unexpected url {url}"


def test_probe_apt_success_updates_metrics() -> None:
    upstream = {
        "name": "ubuntu-test",
        "url": "http://archive.example/ubuntu",
        "format": "apt",
        "layout": "classic",
        "path_prefix": "/ubuntu",
        "suites": ["noble"],
        "components": ["main"],
        "archs": ["amd64"],
    }
    with patch("repo_man.health.fetch_url", side_effect=_fake_fetch):
        result = probe_upstream(upstream, public_base_url="http://mirror")
    assert result.healthy
    assert result.metadata_ok and result.package_ok
    assert result.error is None
    apply_health_metrics([result])
    metrics = get_metrics_output()
    assert "repo_man_upstream_up" in metrics
    assert 'upstream="ubuntu-test"' in metrics


def test_probe_apt_html_proxy_page() -> None:
    upstream = {
        "name": "blocked",
        "url": "http://archive.example/ubuntu",
        "format": "apt",
        "layout": "classic",
        "path_prefix": "/ubuntu",
        "suites": ["noble"],
        "components": ["main"],
        "archs": ["amd64"],
    }

    def html_fetch(url: str, **kwargs):
        return b"<!DOCTYPE html><html><body>Access Denied</body></html>", None

    with patch("repo_man.health.fetch_url", side_effect=html_fetch):
        result = probe_upstream(upstream)
    assert not result.healthy
    assert result.error is not None
    assert "HTML" in result.error or "proxy" in result.error.lower()


def test_probe_apt_ssl_error() -> None:
    upstream = {
        "name": "ssl-fail",
        "url": "https://archive.example/ubuntu",
        "format": "apt",
        "layout": "classic",
        "path_prefix": "/ubuntu",
        "suites": ["noble"],
        "components": ["main"],
        "archs": ["amd64"],
    }

    def ssl_fetch(url: str, **kwargs):
        return None, "SSL error: CERTIFICATE_VERIFY_FAILED"

    with patch("repo_man.health.fetch_url", side_effect=ssl_fetch):
        result = probe_upstream(upstream)
    assert not result.healthy
    assert result.error and "SSL" in result.error


def test_probe_apt_metadata_ok_package_fail() -> None:
    upstream = {
        "name": "pkg-fail",
        "url": "http://archive.example/ubuntu",
        "format": "apt",
        "layout": "classic",
        "path_prefix": "/ubuntu",
        "suites": ["noble"],
        "components": ["main"],
        "archs": ["amd64"],
    }

    def partial(url: str, **kwargs):
        if "Release" in url or "InRelease" in url:
            return b"Origin: Ubuntu\nSuite: noble\n", None
        if "Packages" in url:
            body = b"Package: x\nFilename: pool/main/x/x_1_amd64.deb\nSize: 10\n\n"
            return gzip.compress(body), None
        return None, "SSL error: self signed certificate in certificate chain"

    with patch("repo_man.health.fetch_url", side_effect=partial):
        result = probe_upstream(upstream)
    assert result.metadata_ok
    assert not result.package_ok
    assert not result.healthy
    assert result.error and "package:" in result.error


def _apkindex_tar_gz(text: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name="APKINDEX")
        info.size = len(text)
        tar.addfile(info, io.BytesIO(text))
    return buf.getvalue()


def test_probe_alpine_success() -> None:
    upstream = {
        "name": "alpine-test",
        "url": "http://dl.example/alpine/v3.19/main/x86_64",
        "format": "alpine",
        "path_prefix": "/alpine",
    }
    index = _apkindex_tar_gz(b"P:musl\nV:1.2.4-r2\nS:100\n\n")

    def alpine_fetch(url: str, **kwargs):
        if url.endswith("APKINDEX.tar.gz"):
            return index, None
        if url.endswith(".apk"):
            return b"\x1f\x8b" + b"\x00" * 20, None
        return None, f"unexpected {url}"

    with patch("repo_man.health.fetch_url", side_effect=alpine_fetch):
        result = probe_upstream(upstream)
    assert result.healthy


def test_probe_rpm_success() -> None:
    upstream = {
        "name": "rocky-test",
        "url": "http://dl.example/rocky/9/BaseOS/x86_64/os",
        "format": "rpm",
        "path_prefix": "/rocky9",
    }
    repomd = (
        b'<?xml version="1.0"?>'
        b'<repomd xmlns="http://linux.duke.edu/metadata/repo">'
        b'<data type="primary"><location href="repodata/primary.xml.gz"/></data>'
        b"</repomd>"
    )
    primary = (
        b'<?xml version="1.0"?>'
        b'<metadata xmlns="http://linux.duke.edu/metadata/common">'
        b'<package type="rpm">'
        b'<location href="Packages/tiny-1.0-1.x86_64.rpm"/>'
        b'<size package="64"/>'
        b"</package>"
        b"</metadata>"
    )

    def rpm_fetch(url: str, **kwargs):
        if url.endswith("repomd.xml"):
            return repomd, None
        if "primary.xml" in url:
            return gzip.compress(primary), None
        if url.endswith(".rpm"):
            return b"\xed\xab\xee\xdb" + b"\x00" * 20, None
        return None, f"unexpected {url}"

    with patch("repo_man.health.fetch_url", side_effect=rpm_fetch):
        result = probe_upstream(upstream)
    assert result.healthy
