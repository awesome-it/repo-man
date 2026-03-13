"""Local filesystem storage backend."""

from __future__ import annotations

import logging
from pathlib import Path, PurePath
from typing import BinaryIO, Iterator

from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class LocalStorageBackend(StorageBackend):
    """Store repo data under a root directory on the local filesystem."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _full_path(self, path: str | PurePath) -> Path:
        p = Path(path)
        if p.is_absolute():
            p = p.relative_to("/")
        full = (self._root / p).resolve()
        if not str(full).startswith(str(self._root.resolve())):
            logger.error("Path escapes root: path=%s root=%s", path, self._root)
            raise ValueError(f"Path escapes root: {path}")
        return full

    def get(self, path: str | PurePath) -> bytes | None:
        full = self._full_path(path)
        if not full.exists() or not full.is_file():
            return None
        return full.read_bytes()

    def put(self, path: str | PurePath, data: bytes | BinaryIO) -> None:
        full = self._full_path(path)
        full.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            full.write_bytes(data)
        else:
            full.write_bytes(data.read())

    def list_prefix(self, prefix: str | PurePath) -> Iterator[str]:
        base = self._full_path(prefix)
        if not base.exists() or not base.is_dir():
            return
        root_resolved = self._root.resolve()
        for f in base.rglob("*"):
            if f.is_file():
                rel = f.relative_to(root_resolved)
                yield str(rel.as_posix())

    def delete(self, path: str | PurePath) -> bool:
        full = self._full_path(path)
        if not full.exists():
            return False
        if full.is_file():
            full.unlink()
            return True
        # Directory: remove recursively
        import shutil
        shutil.rmtree(full)
        return True

    def exists(self, path: str | PurePath) -> bool:
        full = self._full_path(path)
        return full.exists()
