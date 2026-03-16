"""Unit tests for RPM version comparison."""

import pytest

from repo_man.formats.rpm.version import compare_versions


def test_compare_equal() -> None:
    assert compare_versions("1.0", "1.0") == 0
    assert compare_versions("1.0-1", "1.0-1") == 0


def test_compare_less() -> None:
    assert compare_versions("1.0", "2.0") == -1
    assert compare_versions("1.0", "1.1") == -1
    assert compare_versions("1.0-1", "1.0-2") == -1


def test_compare_greater() -> None:
    assert compare_versions("2.0", "1.0") == 1
    assert compare_versions("1.1", "1.0") == 1


def test_compare_epoch() -> None:
    assert compare_versions("1:1.0", "2.0") == 1
    assert compare_versions("2.0", "1:1.0") == -1


def test_compare_release() -> None:
    assert compare_versions("1.0-1", "1.0-2") == -1
    assert compare_versions("1.0-10", "1.0-9") == 1
