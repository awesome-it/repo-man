"""FastAPI dependencies (e.g. storage from app state)."""

from __future__ import annotations

from fastapi import Request

from repo_man.storage.base import StorageBackend


def get_storage(request: Request) -> StorageBackend:
    """Return the storage backend from app state (set by create_api_app)."""
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise RuntimeError("Storage not configured on app.state")
    return storage
