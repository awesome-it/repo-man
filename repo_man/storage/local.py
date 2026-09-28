"""Local filesystem storage backend."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path, PurePath
from typing import BinaryIO, Iterator

from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)

PARTIAL_SUFFIX = ".partial"


class _PartialFileWriter:
    def __init__(self, partial_path: Path, final_path: Path) -> None:
        self._partial_path = partial_path
        self._final_path = final_path
        self._fh = partial_path.open("wb")

    def write(self, data: bytes) -> None:
        self._fh.write(data)

    def flush(self) -> None:
        self._fh.flush()

    def tell(self) -> int:
        return int(self._fh.tell())

    def close_success(self) -> None:
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._fh.close()
        os.replace(self._partial_path, self._final_path)

    def close_abort(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass
        try:
            if self._partial_path.exists():
                self._partial_path.unlink()
        except OSError:
            pass


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

    def _partial_path(self, path: str | PurePath) -> Path:
        return Path(str(self._full_path(path)) + PARTIAL_SUFFIX)

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

    def open_read(self, path: str | PurePath) -> BinaryIO | None:
        full = self._full_path(path)
        if not full.exists() or not full.is_file():
            return None
        return full.open("rb")

    @contextmanager
    def open_partial_writer(self, path: str | PurePath):
        final = self._full_path(path)
        partial = self._partial_path(path)
        final.parent.mkdir(parents=True, exist_ok=True)
        if partial.exists():
            partial.unlink()
        writer = _PartialFileWriter(partial, final)
        try:
            yield writer
            writer.close_success()
        except BaseException:
            writer.close_abort()
            raise

    def read_partial(self, path: str | PurePath, size: int) -> bytes:
        if size <= 0:
            return b""
        partial = self._partial_path(path)
        if not partial.exists():
            return b""
        with partial.open("rb") as fh:
            return fh.read(size)

    def partial_exists(self, path: str | PurePath) -> bool:
        return self._partial_path(path).exists()

    def list_prefix(self, prefix: str | PurePath) -> Iterator[str]:
        base = self._full_path(prefix)
        if not base.exists() or not base.is_dir():
            return
        root_resolved = self._root.resolve()
        for f in base.rglob("*"):
            if f.is_file():
                # Hide in-progress partials from listing/prune
                if f.name.endswith(PARTIAL_SUFFIX):
                    continue
                rel = f.relative_to(root_resolved)
                yield str(rel.as_posix())

    def delete(self, path: str | PurePath) -> bool:
        full = self._full_path(path)
        partial = self._partial_path(path)
        removed = False
        if partial.exists() and partial.is_file():
            partial.unlink()
            removed = True
        if not full.exists():
            return removed
        if full.is_file():
            full.unlink()
            return True
        import shutil

        shutil.rmtree(full)
        return True

    def exists(self, path: str | PurePath) -> bool:
        full = self._full_path(path)
        return full.exists()
