"""Tests for stream-through pull-through cache (fan-out, disconnect, single-flight)."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from repo_man.formats.pull_through import (
    UpstreamStream,
    get_or_attach_package_stream,
    reset_inflight_for_tests,
)
from repo_man.storage.local import LocalStorageBackend


@pytest.fixture(autouse=True)
def _clear_inflight() -> None:
    reset_inflight_for_tests()
    yield
    reset_inflight_for_tests()


def test_partial_writer_commits(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    with storage.open_partial_writer("cache/u/pool/a.deb") as w:
        w.write(b"hello")
        w.write(b"-world")
    assert storage.get("cache/u/pool/a.deb") == b"hello-world"
    assert storage.partial_exists("cache/u/pool/a.deb") is False


def test_partial_writer_aborts_on_error(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    with pytest.raises(RuntimeError):
        with storage.open_partial_writer("cache/u/pool/a.deb") as w:
            w.write(b"x")
            raise RuntimeError("boom")
    assert storage.get("cache/u/pool/a.deb") is None
    assert storage.partial_exists("cache/u/pool/a.deb") is False


def test_stream_through_first_chunk_before_eof(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    key = "cache/u/pool/pkg.deb"
    gate = threading.Event()
    calls = {"n": 0}

    def fetch() -> UpstreamStream:
        calls["n"] += 1

        def chunks():
            yield b"AAA"
            gate.wait(timeout=5)
            yield b"BBB"

        return UpstreamStream(content_length=6, chunks=chunks())

    stream = get_or_attach_package_stream(storage, key, fetch)
    it = stream.iter_chunks()
    first = next(it)
    assert first == b"AAA"
    assert storage.get(key) is None  # not committed yet
    gate.set()
    rest = b"".join(it)
    assert rest == b"BBB"
    stream.close()
    # Allow fetcher thread to finish rename
    deadline = time.time() + 2
    while time.time() < deadline and storage.get(key) is None:
        time.sleep(0.01)
    assert storage.get(key) == b"AAABBB"
    assert calls["n"] == 1


def test_concurrent_clients_single_upstream(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    key = "cache/u/pool/pkg.deb"
    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def fetch() -> UpstreamStream:
        calls["n"] += 1
        started.set()

        def chunks():
            yield b"ONE"
            release.wait(timeout=5)
            yield b"TWO"

        return UpstreamStream(content_length=6, chunks=chunks())

    results: list[bytes] = []
    errors: list[BaseException] = []

    def client() -> None:
        try:
            s = get_or_attach_package_stream(storage, key, fetch)
            results.append(b"".join(s.iter_chunks()))
            s.close()
        except BaseException as e:
            errors.append(e)

    t1 = threading.Thread(target=client)
    t2 = threading.Thread(target=client)
    t1.start()
    assert started.wait(timeout=2)
    t2.start()
    time.sleep(0.05)  # let second attach mid-flight
    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not errors
    assert results == [b"ONETWO", b"ONETWO"]
    assert calls["n"] == 1
    assert storage.get(key) == b"ONETWO"


def test_disconnect_still_caches(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    key = "cache/u/pool/pkg.deb"
    mid = threading.Event()
    cont = threading.Event()
    calls = {"n": 0}

    def fetch() -> UpstreamStream:
        calls["n"] += 1

        def chunks():
            yield b"LEFT"
            mid.set()
            cont.wait(timeout=5)
            yield b"RIGHT"

        return UpstreamStream(content_length=9, chunks=chunks())

    stream = get_or_attach_package_stream(storage, key, fetch)
    it = stream.iter_chunks()
    assert next(it) == b"LEFT"
    assert mid.wait(timeout=2)
    stream.close()  # client disconnect / unsubscribe
    cont.set()
    deadline = time.time() + 3
    while time.time() < deadline and storage.get(key) is None:
        time.sleep(0.02)
    assert storage.get(key) == b"LEFTRIGHT"
    assert calls["n"] == 1


def test_late_attach_replays_partial_then_live(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    key = "cache/u/pool/pkg.deb"
    after_first = threading.Event()
    release_rest = threading.Event()
    second_ready = threading.Event()
    calls = {"n": 0}

    def fetch() -> UpstreamStream:
        calls["n"] += 1

        def chunks():
            yield b"AAAA"
            after_first.set()
            assert second_ready.wait(timeout=5)
            release_rest.wait(timeout=5)
            yield b"BBBB"

        return UpstreamStream(content_length=8, chunks=chunks())

    bodies: list[bytes] = []

    def first_client() -> None:
        s = get_or_attach_package_stream(storage, key, fetch)
        bodies.append(b"".join(s.iter_chunks()))
        s.close()

    t1 = threading.Thread(target=first_client)
    t1.start()
    assert after_first.wait(timeout=2)

    s2 = get_or_attach_package_stream(storage, key, fetch)
    second_ready.set()
    release_rest.set()
    body2 = b"".join(s2.iter_chunks())
    s2.close()
    t1.join(timeout=5)

    assert bodies == [b"AAAABBBB"]
    assert body2 == b"AAAABBBB"
    assert calls["n"] == 1
    assert storage.get(key) == b"AAAABBBB"


def test_upstream_failure_clears_partial(tmp_path: Path) -> None:
    storage = LocalStorageBackend(tmp_path)
    key = "cache/u/pool/pkg.deb"

    def fetch() -> UpstreamStream:
        def chunks():
            yield b"X"
            raise RuntimeError("upstream boom")

        return UpstreamStream(content_length=None, chunks=chunks())

    stream = get_or_attach_package_stream(storage, key, fetch)
    with pytest.raises(RuntimeError, match="upstream boom"):
        b"".join(stream.iter_chunks())
    stream.close()
    deadline = time.time() + 2
    while time.time() < deadline and storage.partial_exists(key):
        time.sleep(0.01)
    assert storage.get(key) is None
    assert storage.partial_exists(key) is False
