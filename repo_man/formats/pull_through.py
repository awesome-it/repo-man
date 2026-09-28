"""Single-flight pull-through: stream upstream to clients while teeing to cache.

Concurrent misses for the same storage key share one upstream GET. Subscribers
replay bytes already written to the partial file, then receive live chunks.
Client disconnect only unsubscribes; the fetcher always runs to completion.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from repo_man.storage.base import StorageBackend

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
# Slow clients that can't accept chunks within this many seconds are dropped.
SUBSCRIBER_PUT_TIMEOUT_S = 60.0

_EOF = object()
_registry_lock = threading.Lock()
_inflight: dict[str, "InflightFetcher"] = {}


@dataclass
class UpstreamStream:
    """Result of opening an upstream package download."""

    content_length: int | None
    chunks: Iterator[bytes]


FetchUpstreamFn = Callable[[], UpstreamStream]


class Subscriber:
    """One client attached to an InflightFetcher."""

    def __init__(self, replay: bytes) -> None:
        self._replay = replay
        self._q: queue.Queue[Any] = queue.Queue(maxsize=8)
        self._closed = False
        self._close_lock = threading.Lock()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        # Unblock iter_chunks if waiting (best-effort; timeout path also checks closed)
        try:
            self._q.put_nowait(_EOF)
        except queue.Full:
            pass

    def _offer(self, item: Any) -> bool:
        """Push live item; return False if subscriber should be dropped."""
        if self._closed:
            return False
        try:
            self._q.put(item, timeout=SUBSCRIBER_PUT_TIMEOUT_S)
            return True
        except queue.Full:
            logger.warning("Dropping slow package-stream subscriber (queue full)")
            self.close()
            return False

    def iter_chunks(self) -> Iterator[bytes]:
        # Replay bytes already on disk at subscribe time
        offset = 0
        while offset < len(self._replay):
            if self._closed:
                return
            end = min(offset + CHUNK_SIZE, len(self._replay))
            yield self._replay[offset:end]
            offset = end
        while True:
            if self._closed:
                return
            try:
                item = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is _EOF or self._closed:
                return
            if isinstance(item, BaseException):
                raise item
            yield item


class InflightFetcher:
    """Owns one upstream download, partial file, and fan-out to subscribers."""

    def __init__(
        self,
        storage: StorageBackend,
        key: str,
        fetch_upstream: FetchUpstreamFn,
        *,
        on_success: Callable[[], None] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        self.storage = storage
        self.key = key
        self._fetch_upstream = fetch_upstream
        self._on_success = on_success
        self._on_error = on_error
        self._lock = threading.Lock()
        self._subscribers: list[Subscriber] = []
        self._bytes_written = 0
        self.content_length: int | None = None
        self._headers_ready = threading.Event()
        self._done = threading.Event()
        self.error: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"pull-through:{key}",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def wait_headers(self, timeout: float | None = 120.0) -> int | None:
        self._headers_ready.wait(timeout=timeout)
        return self.content_length

    def subscribe(self) -> Subscriber:
        with self._lock:
            replay = self.storage.read_partial(self.key, self._bytes_written)
            sub = Subscriber(replay)
            if self._done.is_set():
                # Race: finished between registry lookup and subscribe
                if self.error is not None:
                    sub._offer(self.error)
                sub._offer(_EOF)
                return sub
            self._subscribers.append(sub)
            return sub

    def _snapshot_subscribers(self) -> list[Subscriber]:
        with self._lock:
            return list(self._subscribers)

    def _broadcast_to(self, subs: list[Subscriber], item: Any) -> None:
        for sub in subs:
            sub._offer(item)
        with self._lock:
            self._subscribers = [s for s in self._subscribers if not s.closed]

    def _run(self) -> None:
        try:
            with self.storage.open_partial_writer(self.key) as writer:
                upstream = self._fetch_upstream()
                self.content_length = upstream.content_length
                self._headers_ready.set()
                for chunk in upstream.chunks:
                    if not chunk:
                        continue
                    writer.write(chunk)
                    writer.flush()
                    # Update length and snapshot under one lock so late joiners either
                    # replay this chunk from disk or are included in the live fan-out.
                    with self._lock:
                        self._bytes_written += len(chunk)
                        subs = list(self._subscribers)
                    self._broadcast_to(subs, chunk)
            # partial writer commits (rename) on clean exit
            if self._on_success is not None:
                self._on_success()
            self._broadcast_to(self._snapshot_subscribers(), _EOF)
        except BaseException as e:
            self.error = e
            self._headers_ready.set()
            if self._on_error is not None:
                try:
                    self._on_error(e)
                except Exception:
                    pass
            subs = self._snapshot_subscribers()
            self._broadcast_to(subs, e)
            self._broadcast_to(self._snapshot_subscribers(), _EOF)
            logger.warning("Pull-through fetch failed: key=%s error=%s", self.key, e)
        finally:
            self._done.set()
            with _registry_lock:
                if _inflight.get(self.key) is self:
                    del _inflight[self.key]


@dataclass
class PackageStream:
    """Stream handle returned to the HTTP layer."""

    content_length: int | None
    from_upstream: bool
    _chunks: Iterator[bytes]
    _close: Callable[[], None] | None = None

    def iter_chunks(self) -> Iterator[bytes]:
        return self._chunks

    def close(self) -> None:
        if self._close is not None:
            self._close()


def _file_stream(storage: StorageBackend, key: str) -> PackageStream:
    fh = storage.open_read(key)
    if fh is None:
        raise FileNotFoundError(key)
    # Size for Content-Length
    try:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(0)
    except Exception:
        size = None

    def _iter() -> Iterator[bytes]:
        try:
            while True:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk
        finally:
            fh.close()

    return PackageStream(content_length=size, from_upstream=False, _chunks=_iter(), _close=fh.close)


def get_or_attach_package_stream(
    storage: StorageBackend,
    key: str,
    fetch_upstream: FetchUpstreamFn,
    *,
    on_success: Callable[[], None] | None = None,
    on_error: Callable[[BaseException], None] | None = None,
) -> PackageStream:
    """
    Return a package byte stream from cache or an in-flight / new upstream fetch.

    Concurrent callers for ``key`` share one upstream download. Late joiners replay
    the partial file then follow live chunks.
    """
    if storage.exists(key):
        return _file_stream(storage, key)

    with _registry_lock:
        # Re-check after lock: another fetcher may have finished
        if storage.exists(key):
            return _file_stream(storage, key)
        fetcher = _inflight.get(key)
        created = False
        if fetcher is None:
            fetcher = InflightFetcher(
                storage,
                key,
                fetch_upstream,
                on_success=on_success,
                on_error=on_error,
            )
            _inflight[key] = fetcher
            created = True
        sub = fetcher.subscribe()

    if created:
        fetcher.start()

    # Wait until Content-Length known (or fetch failed early)
    content_length = fetcher.wait_headers()
    if fetcher.error is not None and fetcher._bytes_written == 0 and not storage.exists(key):
        # Failed before any data; surface error when iterating
        pass

    def _close() -> None:
        sub.close()

    return PackageStream(
        content_length=content_length if fetcher.error is None else None,
        from_upstream=True,
        _chunks=sub.iter_chunks(),
        _close=_close,
    )


def reset_inflight_for_tests() -> None:
    """Clear the in-flight registry (unit tests only)."""
    with _registry_lock:
        _inflight.clear()
