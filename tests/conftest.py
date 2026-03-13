"""Pytest fixtures."""

import tempfile
from pathlib import Path

import pytest

from repo_man.storage.local import LocalStorageBackend


@pytest.fixture
def tmp_repo_root(tmp_path: Path) -> Path:
    """Temporary directory as repo root."""
    return tmp_path


@pytest.fixture
def local_storage(tmp_repo_root: Path) -> LocalStorageBackend:
    """Local storage backend with temporary root."""
    return LocalStorageBackend(tmp_repo_root)
