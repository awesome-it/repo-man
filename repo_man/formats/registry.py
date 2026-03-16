"""Format registry: dispatch by format name (apt, rpm, alpine) to backend with get_or_fetch and prune_upstream."""

from __future__ import annotations

from typing import Any, Protocol

from repo_man.storage.base import StorageBackend


class FormatBackendProtocol(Protocol):
    """Backend for a repo format: get_or_fetch and prune_upstream."""

    def get_or_fetch(
        self,
        upstream_id: str,
        path_suffix: str,
        upstream_config: dict[str, Any],
        storage: StorageBackend,
        package_hash_store: Any = None,
    ) -> tuple[bytes | None, bool]:
        """Return (data, from_upstream). from_upstream True if data was fetched from upstream."""
        ...

    def prune_upstream(
        self,
        storage: StorageBackend,
        upstream_id: str,
        keep_versions_per_package: int,
    ) -> int:
        """Remove old package versions. Return number of packages removed."""
        ...


_BACKENDS: dict[str, FormatBackendProtocol] = {}


def register(name: str, backend: FormatBackendProtocol) -> None:
    _BACKENDS[name] = backend


def get_backend(format_name: str) -> FormatBackendProtocol:
    name = (format_name or "apt").strip().lower()
    if name not in _BACKENDS:
        raise ValueError(f"Unknown format: {format_name!r}. Supported: {list(_BACKENDS.keys())}")
    return _BACKENDS[name]


def supported_formats() -> list[str]:
    return list(_BACKENDS.keys())


# Register APT (always available)
from repo_man.formats.apt import backend as apt_backend_module  # noqa: E402

register("apt", apt_backend_module.backend)

# Register RPM
from repo_man.formats.rpm.backend import backend as rpm_backend  # noqa: E402

register("rpm", rpm_backend)

# Register Alpine
from repo_man.formats.alpine.backend import backend as alpine_backend  # noqa: E402

register("alpine", alpine_backend)
