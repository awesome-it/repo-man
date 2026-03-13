"""Redis-backed package hash store."""

from __future__ import annotations

import logging
from typing import Any

from repo_man.hash_store.base import PackageHashStore

logger = logging.getLogger(__name__)

_KEY_PREFIX = "repo_man:phash:"
_LAST_SERVED_PREFIX = "repo_man:last_served:"


class RedisPackageHashStore(PackageHashStore):
    """Store (upstream_id, path) -> hash in Redis. Keys: repo_man:phash:{upstream_id}:{path}."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", **kwargs: Any) -> None:
        try:
            import redis
        except ImportError:
            raise ImportError("Redis backend requires the 'redis' package. Install with: pip install redis") from None
        self._client = redis.from_url(redis_url, decode_responses=True, **kwargs)

    def _key(self, upstream_id: str, path: str) -> str:
        return f"{_KEY_PREFIX}{upstream_id}:{path}"

    def _prefix(self, upstream_id: str) -> str:
        return f"{_KEY_PREFIX}{upstream_id}:"

    def get(self, upstream_id: str, path: str) -> str | None:
        val = self._client.get(self._key(upstream_id, path))
        return val if val is not None else None

    def set(self, upstream_id: str, path: str, hash_value: str) -> None:
        self._client.set(self._key(upstream_id, path), hash_value)

    def delete(self, upstream_id: str, path: str) -> None:
        self._client.delete(self._key(upstream_id, path))
        self._client.delete(self._last_served_key(upstream_id, path))

    def _last_served_key(self, upstream_id: str, path: str) -> str:
        return f"{_LAST_SERVED_PREFIX}{upstream_id}:{path}"

    def set_last_served(self, upstream_id: str, path: str, timestamp: float) -> None:
        self._client.set(self._last_served_key(upstream_id, path), str(timestamp))

    def get_last_served(self, upstream_id: str, path: str) -> float | None:
        val = self._client.get(self._last_served_key(upstream_id, path))
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def list_paths(self, upstream_id: str) -> list[str]:
        prefix = self._prefix(upstream_id)
        out: list[str] = []
        for key in self._client.scan_iter(match=f"{prefix}*"):
            if key.startswith(prefix):
                out.append(key[len(prefix) :])
        return out
