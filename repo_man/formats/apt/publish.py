"""Publish .deb packages: generate Packages and Release under a path prefix."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path, PurePath
from typing import Any

from repo_man.formats.apt.deb_control import control_to_packages_stanza, get_deb_control
from repo_man.formats.apt.metadata import generate_packages, generate_release
from repo_man.storage.base import StorageBackend


def _pool_path(component: str, arch: str, filename: str) -> str:
    """Standard pool path: pool/component/arch/package_filename.deb or pool/component/letter/package/."""
    # Simple: pool/<component>/<arch>/<filename>
    return f"pool/{component}/{arch}/{filename}"


def publish_packages(
    path_prefix: str,
    deb_paths: list[Path],
    suite: str,
    component: str,
    arch: str,
    storage: StorageBackend,
) -> bool:
    """
    Ingest .deb files, generate Packages and Release under path_prefix.
    path_prefix is the logical prefix (e.g. "local"); we store under local/<suite>/...
    Returns True if any change was made.
    """
    prefix = path_prefix.strip("/") or "local"
    stanzas: list[dict[str, str]] = []
    changed = False
    for p in deb_paths:
        if not p.suffix == ".deb":
            continue
        control = get_deb_control(p)
        if not control:
            continue
        filename = p.name
        rel_path = _pool_path(component, arch, filename)
        storage_key = f"{prefix}/pool/{component}/{arch}/{filename}"
        existing = storage.get(storage_key)
        data = p.read_bytes()
        if existing != data:
            storage.put(storage_key, data)
            changed = True
        stanza = control_to_packages_stanza(control, rel_path)
        stanzas.append(stanza)
    if not stanzas:
        return False
    # Generate Packages (plain and gzip)
    packages_content = generate_packages(stanzas)
    packages_bytes = packages_content.encode("utf-8")
    packages_gz_bytes = gzip.compress(packages_bytes)
    dists_base = f"{prefix}/dists/{suite}/{component}/binary-{arch}"
    storage.put(f"{dists_base}/Packages", packages_bytes)
    storage.put(f"{dists_base}/Packages.gz", packages_gz_bytes)
    # Release file: paths relative to Release (dists/suite/)
    rel_packages = f"{component}/binary-{arch}/Packages"
    rel_packages_gz = f"{component}/binary-{arch}/Packages.gz"
    md5_sums = {
        rel_packages: (hashlib.md5(packages_bytes).hexdigest(), len(packages_bytes)),
        rel_packages_gz: (hashlib.md5(packages_gz_bytes).hexdigest(), len(packages_gz_bytes)),
    }
    sha256_sums = {
        rel_packages: (hashlib.sha256(packages_bytes).hexdigest(), len(packages_bytes)),
        rel_packages_gz: (hashlib.sha256(packages_gz_bytes).hexdigest(), len(packages_gz_bytes)),
    }
    release_content = generate_release(
        architectures=[arch],
        components=[component],
        suite=suite,
        codename=suite,
        origin="repo-man",
        label="repo-man",
        md5_sums=md5_sums,
        sha256_sums=sha256_sums,
    )
    storage.put(f"{prefix}/dists/{suite}/Release", release_content.encode("utf-8"))
    return True
