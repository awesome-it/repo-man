"""Upstream health probes, status persistence, and Prometheus gauge updates."""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import tarfile
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from repo_man.metrics import (
    upstream_last_check_timestamp_seconds,
    upstream_up,
)
from repo_man.upstream_http import (
    fetch_url,
    format_unexpected_content_error,
    looks_like_apk,
    looks_like_apt_release,
    looks_like_deb,
    looks_like_gzip,
    looks_like_html,
    looks_like_rpm,
    looks_like_xml,
    resolve_upstream_auth,
)

logger = logging.getLogger(__name__)

STATUS_FILENAME = "upstream_status.json"
PLACEHOLDER_BASE = "http://<mirror-host>"
PACKAGE_SIZE_CAP_BYTES = 5 * 1024 * 1024  # prefer packages under 5 MiB


@dataclass
class UpstreamHealthResult:
    name: str
    path_prefix: str
    format: str
    healthy: bool
    metadata_ok: bool
    package_ok: bool
    checked_at: float
    error: str | None = None
    client_urls: list[str] = field(default_factory=list)
    metadata_error: str | None = None
    package_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UpstreamHealthResult:
        return cls(
            name=str(data.get("name") or ""),
            path_prefix=str(data.get("path_prefix") or "/"),
            format=str(data.get("format") or "apt"),
            healthy=bool(data.get("healthy")),
            metadata_ok=bool(data.get("metadata_ok")),
            package_ok=bool(data.get("package_ok")),
            checked_at=float(data.get("checked_at") or 0),
            error=data.get("error"),
            client_urls=list(data.get("client_urls") or []),
            metadata_error=data.get("metadata_error"),
            package_error=data.get("package_error"),
        )


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [s.strip() for s in value.split(",") if s.strip()]
    return [str(s).strip() for s in value if str(s).strip()]


def _base_url(upstream: dict[str, Any]) -> str:
    return (upstream.get("url") or upstream.get("base_url") or "").rstrip("/")


def _path_prefix(upstream: dict[str, Any]) -> str:
    p = (upstream.get("path_prefix") or "/").rstrip("/") or ""
    return p if p.startswith("/") else f"/{p}"


def build_client_urls(upstream: dict[str, Any], public_base_url: str | None) -> list[str]:
    """Build example client lines for this upstream."""
    base = (public_base_url or "").rstrip("/")
    if not base:
        base = PLACEHOLDER_BASE
    prefix = _path_prefix(upstream)
    repo_url = f"{base}{prefix}"
    fmt = str(upstream.get("format") or "apt").strip().lower()

    if fmt == "rpm":
        return [f"baseurl={repo_url}"]
    if fmt == "alpine":
        return [f"{repo_url}"]

    # APT
    layout = str(upstream.get("layout") or "classic").strip().lower()
    if layout == "single-stream":
        return [f"deb {repo_url} ./"]
    suites = _normalize_list(upstream.get("suites")) or ["stable"]
    components = _normalize_list(upstream.get("components")) or ["main"]
    comp = " ".join(components)
    return [f"deb {repo_url} {suite} {comp}" for suite in suites]


def status_path(repo_root: Path | str) -> Path:
    return Path(repo_root) / STATUS_FILENAME


def save_status(repo_root: Path | str, results: list[UpstreamHealthResult]) -> Path:
    """Atomically write upstream status JSON under repo_root."""
    path = status_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": time.time(),
        "upstreams": [r.to_dict() for r in results],
    }
    data = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".upstream_status.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def load_status(repo_root: Path | str) -> dict[str, Any] | None:
    """Load status file; return None if missing or invalid."""
    path = status_path(repo_root)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as e:
        logger.warning("Could not load upstream status: path=%s error=%s", path, e)
        return None


def apply_health_metrics(results: list[UpstreamHealthResult]) -> None:
    """Update Prometheus gauges from probe results."""
    for r in results:
        upstream_up.labels(upstream=r.name).set(1 if r.healthy else 0)
        upstream_last_check_timestamp_seconds.labels(upstream=r.name).set(r.checked_at)


def init_health_metrics(upstreams: list[dict[str, Any]]) -> None:
    """Ensure a series exists for each configured upstream (starts as down until first probe)."""
    now = time.time()
    for u in upstreams:
        name = str(u.get("name") or "").strip()
        if not name:
            continue
        upstream_up.labels(upstream=name).set(0)
        upstream_last_check_timestamp_seconds.labels(upstream=name).set(0)


def _pick_smallest_package(
    candidates: list[tuple[str, int | None]],
    size_cap: int = PACKAGE_SIZE_CAP_BYTES,
) -> str | None:
    """candidates: (relative_path, size_or_None). Prefer known size under cap, else first."""
    with_size = [(p, s) for p, s in candidates if s is not None and s > 0]
    under_cap = [(p, s) for p, s in with_size if s <= size_cap]
    if under_cap:
        under_cap.sort(key=lambda x: x[1])
        return under_cap[0][0]
    if with_size:
        with_size.sort(key=lambda x: x[1])
        return with_size[0][0]
    if candidates:
        return candidates[0][0]
    return None


def _parse_apt_packages_sample(raw: bytes) -> list[tuple[str, int | None]]:
    """Return list of (Filename, Size) from Packages / Packages.gz."""
    if looks_like_gzip(raw):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return []
    if looks_like_html(raw):
        return []
    text = raw.decode("utf-8", errors="replace")
    out: list[tuple[str, int | None]] = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        filename: str | None = None
        size: int | None = None
        for line in block.split("\n"):
            if line.startswith("Filename:"):
                filename = line.split(":", 1)[1].strip()
            elif line.startswith("Size:"):
                try:
                    size = int(line.split(":", 1)[1].strip())
                except ValueError:
                    size = None
        if filename:
            out.append((filename, size))
    return out


def _probe_apt(
    upstream: dict[str, Any],
    headers: dict[str, str] | None,
    auth: tuple[str, str] | None,
) -> tuple[bool, bool, str | None, str | None]:
    base = _base_url(upstream)
    if not base:
        return False, False, "No upstream URL configured", None

    layout = str(upstream.get("layout") or "classic").strip().lower()
    suites = _normalize_list(upstream.get("suites"))
    components = _normalize_list(upstream.get("components")) or ["main"]
    archs = _normalize_list(upstream.get("archs")) or ["amd64"]
    suite = suites[0] if suites else None
    component = components[0]
    arch = archs[0]

    metadata_ok = False
    package_ok = False
    metadata_error: str | None = None
    package_error: str | None = None

    if layout == "single-stream":
        release_paths = ["InRelease", "Release"]
        packages_paths = ["Packages.gz", "Packages"]
    else:
        if not suite:
            return False, False, "APT classic upstream has no suites configured", None
        release_paths = [f"dists/{suite}/InRelease", f"dists/{suite}/Release"]
        packages_paths = [
            f"dists/{suite}/{component}/binary-{arch}/Packages.gz",
            f"dists/{suite}/{component}/binary-{arch}/Packages",
        ]

    release_ok = False
    for path in release_paths:
        url = f"{base}/{path}"
        data, err = fetch_url(url, headers=headers, auth=auth, timeout=30.0)
        if err:
            metadata_error = err
            continue
        assert data is not None
        if not looks_like_apt_release(data):
            metadata_error = format_unexpected_content_error(url, "APT Release/InRelease", data)
            continue
        release_ok = True
        metadata_ok = True
        metadata_error = None
        break

    if not release_ok or not metadata_ok:
        return False, False, metadata_error or "Metadata fetch failed", None

    packages_data: bytes | None = None
    packages_url = ""
    for path in packages_paths:
        url = f"{base}/{path}"
        data, err = fetch_url(url, headers=headers, auth=auth, timeout=60.0)
        if err:
            package_error = f"Packages index: {err}"
            continue
        assert data is not None
        if looks_like_html(data):
            package_error = format_unexpected_content_error(url, "Packages index", data)
            continue
        if path.endswith(".gz") and not looks_like_gzip(data):
            package_error = format_unexpected_content_error(url, "Packages.gz (gzip)", data)
            continue
        packages_data = data
        packages_url = url
        package_error = None
        break

    if packages_data is None:
        # Metadata OK but packages index failed — still report package failure
        return True, False, None, package_error or f"Could not fetch Packages index near {base}"

    candidates = _parse_apt_packages_sample(packages_data)
    pkg_path = _pick_smallest_package(candidates)
    if not pkg_path:
        return True, False, None, f"No packages listed in {packages_url}"

    pkg_url = f"{base}/{pkg_path.lstrip('/')}"
    pkg_data, err = fetch_url(pkg_url, headers=headers, auth=auth, timeout=120.0)
    if err:
        return True, False, None, err
    assert pkg_data is not None
    if not looks_like_deb(pkg_data):
        return True, False, None, format_unexpected_content_error(pkg_url, ".deb package", pkg_data)
    return True, True, None, None


def _parse_repomd_primary_href(repomd: bytes) -> str | None:
    try:
        root = ET.fromstring(repomd)
    except ET.ParseError:
        return None
    # Handle default namespace
    for data in root.iter():
        tag = data.tag.split("}")[-1] if "}" in data.tag else data.tag
        if tag != "data":
            continue
        if data.attrib.get("type") != "primary":
            continue
        for child in data:
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "location":
                href = child.attrib.get("href")
                if href:
                    return href
    return None


def _parse_rpm_primary_packages(primary_raw: bytes) -> list[tuple[str, int | None]]:
    raw = primary_raw
    if looks_like_gzip(raw):
        try:
            raw = gzip.decompress(raw)
        except OSError:
            return []
    if looks_like_html(raw):
        return []
    # Fast path: regex for href and size (avoids heavy full XML dependency issues)
    out: list[tuple[str, int | None]] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # Fallback regex
        for m in re.finditer(rb'href="([^"]+\.rpm)"', raw):
            out.append((m.group(1).decode("utf-8", errors="replace"), None))
        return out

    for pkg in root.iter():
        tag = pkg.tag.split("}")[-1] if "}" in pkg.tag else pkg.tag
        if tag != "package":
            continue
        href: str | None = None
        size: int | None = None
        for child in pkg.iter():
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "location":
                href = child.attrib.get("href")
            elif ctag == "size":
                package_size = child.attrib.get("package")
                if package_size and package_size.isdigit():
                    size = int(package_size)
        if href and href.endswith(".rpm"):
            out.append((href, size))
    return out


def _probe_rpm(
    upstream: dict[str, Any],
    headers: dict[str, str] | None,
    auth: tuple[str, str] | None,
) -> tuple[bool, bool, str | None, str | None]:
    base = _base_url(upstream)
    if not base:
        return False, False, "No upstream URL configured", None

    repomd_url = f"{base}/repodata/repomd.xml"
    data, err = fetch_url(repomd_url, headers=headers, auth=auth, timeout=60.0)
    if err:
        return False, False, err, None
    assert data is not None
    if not looks_like_xml(data) or b"repomd" not in data[:500].lower():
        return False, False, format_unexpected_content_error(repomd_url, "repomd.xml", data), None

    primary_href = _parse_repomd_primary_href(data)
    if not primary_href:
        return True, False, None, "repomd.xml has no primary metadata location"

    primary_url = f"{base}/{primary_href.lstrip('/')}"
    primary_data, err = fetch_url(primary_url, headers=headers, auth=auth, timeout=120.0)
    if err:
        return True, False, None, f"primary metadata: {err}"
    assert primary_data is not None
    if looks_like_html(primary_data):
        return True, False, None, format_unexpected_content_error(primary_url, "primary.xml", primary_data)

    candidates = _parse_rpm_primary_packages(primary_data)
    pkg_path = _pick_smallest_package(candidates)
    if not pkg_path:
        return True, False, None, f"No packages listed in {primary_url}"

    pkg_url = f"{base}/{pkg_path.lstrip('/')}"
    pkg_data, err = fetch_url(pkg_url, headers=headers, auth=auth, timeout=120.0)
    if err:
        return True, False, None, err
    assert pkg_data is not None
    if not looks_like_rpm(pkg_data):
        return True, False, None, format_unexpected_content_error(pkg_url, ".rpm package", pkg_data)
    return True, True, None, None


def _parse_apkindex_packages(raw: bytes) -> list[tuple[str, int | None]]:
    """Parse APKINDEX.tar.gz or APKINDEX text; return (filename.apk, size)."""
    data = raw
    if looks_like_gzip(data):
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
                member = None
                for m in tar.getmembers():
                    if m.isfile() and (m.name.endswith("APKINDEX") or m.name == "APKINDEX"):
                        member = m
                        break
                if member is None:
                    # first regular file
                    for m in tar.getmembers():
                        if m.isfile():
                            member = m
                            break
                if member is None:
                    return []
                f = tar.extractfile(member)
                if f is None:
                    return []
                data = f.read()
        except (tarfile.TarError, OSError):
            try:
                data = gzip.decompress(raw)
            except OSError:
                return []
    if looks_like_html(data):
        return []
    text = data.decode("utf-8", errors="replace")
    out: list[tuple[str, int | None]] = []
    name: str | None = None
    version: str | None = None
    size: int | None = None
    for line in text.splitlines():
        if line == "":
            if name and version:
                out.append((f"{name}-{version}.apk", size))
            name, version, size = None, None, None
            continue
        if line.startswith("P:"):
            name = line[2:].strip()
        elif line.startswith("V:"):
            version = line[2:].strip()
        elif line.startswith("S:"):
            try:
                size = int(line[2:].strip())
            except ValueError:
                size = None
    if name and version:
        out.append((f"{name}-{version}.apk", size))
    return out


def _probe_alpine(
    upstream: dict[str, Any],
    headers: dict[str, str] | None,
    auth: tuple[str, str] | None,
) -> tuple[bool, bool, str | None, str | None]:
    base = _base_url(upstream)
    if not base:
        return False, False, "No upstream URL configured", None

    index_data: bytes | None = None
    index_url = ""
    metadata_error: str | None = None
    for name in ("APKINDEX.tar.gz", "APKINDEX.xml"):
        url = f"{base}/{name}"
        data, err = fetch_url(url, headers=headers, auth=auth, timeout=60.0)
        if err:
            metadata_error = err
            continue
        assert data is not None
        if looks_like_html(data):
            metadata_error = format_unexpected_content_error(url, "APKINDEX", data)
            continue
        if name.endswith(".gz") and not looks_like_gzip(data):
            metadata_error = format_unexpected_content_error(url, "APKINDEX.tar.gz (gzip)", data)
            continue
        index_data = data
        index_url = url
        metadata_error = None
        break

    if index_data is None:
        return False, False, metadata_error or "APKINDEX fetch failed", None

    candidates = _parse_apkindex_packages(index_data)
    pkg_path = _pick_smallest_package(candidates)
    if not pkg_path:
        return True, False, None, f"No packages listed in {index_url}"

    pkg_url = f"{base}/{pkg_path.lstrip('/')}"
    pkg_data, err = fetch_url(pkg_url, headers=headers, auth=auth, timeout=120.0)
    if err:
        return True, False, None, err
    assert pkg_data is not None
    if not looks_like_apk(pkg_data):
        return True, False, None, format_unexpected_content_error(pkg_url, ".apk package", pkg_data)
    return True, True, None, None


def probe_upstream(
    upstream: dict[str, Any],
    public_base_url: str | None = None,
) -> UpstreamHealthResult:
    """Probe one upstream: metadata + sample package. Healthy only if both succeed."""
    name = str(upstream.get("name") or "unknown")
    path_prefix = _path_prefix(upstream)
    fmt = str(upstream.get("format") or "apt").strip().lower()
    client_urls = build_client_urls(upstream, public_base_url)
    checked_at = time.time()
    headers, auth = resolve_upstream_auth(upstream)

    try:
        if fmt == "rpm":
            metadata_ok, package_ok, metadata_error, package_error = _probe_rpm(upstream, headers, auth)
        elif fmt == "alpine":
            metadata_ok, package_ok, metadata_error, package_error = _probe_alpine(upstream, headers, auth)
        else:
            metadata_ok, package_ok, metadata_error, package_error = _probe_apt(upstream, headers, auth)
    except Exception as e:
        logger.warning("Upstream probe crashed: upstream=%s error=%s", name, e)
        return UpstreamHealthResult(
            name=name,
            path_prefix=path_prefix,
            format=fmt,
            healthy=False,
            metadata_ok=False,
            package_ok=False,
            checked_at=checked_at,
            error=f"Probe failed: {e}",
            client_urls=client_urls,
            metadata_error=str(e),
        )

    healthy = metadata_ok and package_ok
    error: str | None = None
    if not healthy:
        parts = []
        if metadata_error:
            parts.append(f"metadata: {metadata_error}")
        if package_error:
            parts.append(f"package: {package_error}")
        if not parts:
            parts.append("unknown failure")
        error = "; ".join(parts)

    return UpstreamHealthResult(
        name=name,
        path_prefix=path_prefix,
        format=fmt,
        healthy=healthy,
        metadata_ok=metadata_ok,
        package_ok=package_ok,
        checked_at=checked_at,
        error=error,
        client_urls=client_urls,
        metadata_error=metadata_error,
        package_error=package_error,
    )


def probe_all_upstreams(
    upstreams: list[dict[str, Any]],
    public_base_url: str | None = None,
) -> list[UpstreamHealthResult]:
    """Probe every configured upstream."""
    results: list[UpstreamHealthResult] = []
    for u in upstreams:
        if not str(u.get("name") or "").strip():
            continue
        results.append(probe_upstream(u, public_base_url=public_base_url))
    return results


def run_health_checks(
    upstreams: list[dict[str, Any]],
    repo_root: Path | str,
    public_base_url: str | None = None,
    *,
    update_metrics: bool = True,
) -> list[UpstreamHealthResult]:
    """Probe all upstreams, persist status JSON, optionally update Prometheus gauges."""
    results = probe_all_upstreams(upstreams, public_base_url=public_base_url)
    save_status(repo_root, results)
    if update_metrics:
        apply_health_metrics(results)
    return results
