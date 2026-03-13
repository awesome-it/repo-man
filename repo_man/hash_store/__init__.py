"""Package hash store backends for verifying cached packages against metadata."""

from __future__ import annotations

from pathlib import Path

from repo_man.hash_store.base import PackageHashStore
from repo_man.hash_store.local import LocalPackageHashStore
from repo_man.hash_store.redis_store import RedisPackageHashStore


def create_package_hash_store(
    store_type: str,
    *,
    redis_url: str = "redis://localhost:6379/0",
    local_db_path: Path | str | None = None,
) -> PackageHashStore:
    """Create a PackageHashStore from type. 'local' uses local_db_path (default repo_root/hash_store.db)."""
    if store_type == "redis":
        return RedisPackageHashStore(redis_url=redis_url)
    if store_type == "local":
        path = local_db_path or "hash_store.db"
        return LocalPackageHashStore(db_path=path)
    raise ValueError(f"Unknown package_hash_store type: {store_type!r}")


__all__ = [
    "PackageHashStore",
    "LocalPackageHashStore",
    "RedisPackageHashStore",
    "create_package_hash_store",
]
