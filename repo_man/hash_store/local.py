"""Local SQLite-backed package hash store."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from repo_man.hash_store.base import PackageHashStore


class LocalPackageHashStore(PackageHashStore):
    """Store (upstream_id, path) -> hash in a SQLite database."""

    def __init__(self, db_path: Path | str) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # This store is used from request worker threads; serialize access to a single
        # sqlite connection to prevent concurrent use of the same connection object.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(self._path),
            check_same_thread=False,
            timeout=2.0,
        )
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=2000")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS package_hashes "
                "(upstream_id TEXT NOT NULL, path TEXT NOT NULL, hash_value TEXT NOT NULL, "
                "PRIMARY KEY (upstream_id, path))"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS last_served "
                "(upstream_id TEXT NOT NULL, path TEXT NOT NULL, served_at REAL NOT NULL, "
                "PRIMARY KEY (upstream_id, path))"
            )
            self._conn.commit()

    def get(self, upstream_id: str, path: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT hash_value FROM package_hashes WHERE upstream_id = ? AND path = ?",
                (upstream_id, path),
            ).fetchone()
        return row[0] if row else None

    def set(self, upstream_id: str, path: str, hash_value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO package_hashes (upstream_id, path, hash_value) VALUES (?, ?, ?)",
                (upstream_id, path, hash_value),
            )
            self._conn.commit()

    def delete(self, upstream_id: str, path: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM package_hashes WHERE upstream_id = ? AND path = ?",
                (upstream_id, path),
            )
            self._conn.execute(
                "DELETE FROM last_served WHERE upstream_id = ? AND path = ?",
                (upstream_id, path),
            )
            self._conn.commit()

    def set_last_served(self, upstream_id: str, path: str, timestamp: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO last_served (upstream_id, path, served_at) VALUES (?, ?, ?)",
                (upstream_id, path, timestamp),
            )
            self._conn.commit()

    def get_last_served(self, upstream_id: str, path: str) -> float | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT served_at FROM last_served WHERE upstream_id = ? AND path = ?",
                (upstream_id, path),
            ).fetchone()
        return float(row[0]) if row else None

    def list_paths(self, upstream_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT path FROM package_hashes WHERE upstream_id = ?",
                (upstream_id,),
            ).fetchall()
        return [r[0] for r in rows]
