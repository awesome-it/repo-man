"""Unit tests for Alpine version comparison."""

import pytest

from repo_man.formats.alpine.version import compare_versions


def test_compare_equal() -> None:
    assert compare_versions("1.0", "1.0") == 0
    assert compare_versions("1.0.0-r0", "1.0.0-r0") == 0


def test_compare_less() -> None:
    assert compare_versions("1.0", "2.0") == -1
    assert compare_versions("1.0", "1.1") == -1


def test_compare_greater() -> None:
    assert compare_versions("2.0", "1.0") == 1
    assert compare_versions("1.1", "1.0") == 1


def test_compare_with_r_revision() -> None:
    # version-rN: we strip -rN for comparison, so 1.0.0-r0 == 1.0.0
    assert compare_versions("1.0.0-r0", "1.0.0-r1") == 0  # same base version
    assert compare_versions("1.0.0", "1.0.1") == -1
