"""Request queue gate for LAN-facing RAG endpoints."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueSnapshot:
    """Point-in-time view of the RAG request queue."""

    active: int
    waiting: int
    max_concurrent: int
    max_queue_depth: int

    @property
    def capacity(self) -> int:
        """Maximum admitted requests (active + waiting)."""
        return self.max_concurrent + self.max_queue_depth

    @property
    def admitted(self) -> int:
        """Requests currently active or waiting for an active slot."""
        return self.active + self.waiting

    @property
    def capacity_remaining(self) -> int:
        """How many more requests can enter the queue."""
        return max(0, self.capacity - self.admitted)


class QueueFullError(Exception):
    """Raised when the RAG queue cannot accept another request."""

    def __init__(self, snapshot: QueueSnapshot, *, retry_after_seconds: int) -> None:
        self.snapshot = snapshot
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            "RAG queue is full "
            f"(active={snapshot.active}, waiting={snapshot.waiting}, "
            f"capacity={snapshot.capacity})"
        )


def queue_response_headers(
    snapshot: QueueSnapshot,
    *,
    retry_after_seconds: int | None = None,
) -> dict[str, str]:
    """Build standard queue visibility headers for HTTP responses."""
    headers = {
        "X-EE-Wiki-Queue-Active": str(snapshot.active),
        "X-EE-Wiki-Queue-Waiting": str(snapshot.waiting),
        "X-EE-Wiki-Queue-Max-Concurrent": str(snapshot.max_concurrent),
        "X-EE-Wiki-Queue-Max-Depth": str(snapshot.max_queue_depth),
        "X-EE-Wiki-Queue-Capacity-Remaining": str(snapshot.capacity_remaining),
    }
    if retry_after_seconds is not None:
        headers["Retry-After"] = str(retry_after_seconds)
    return headers


class RequestQueueGate:
    """Limit concurrent RAG requests and bound the waiting queue."""

    def __init__(
        self,
        *,
        max_concurrent: int,
        max_queue_depth: int,
        retry_after_seconds: int,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if max_queue_depth < 0:
            raise ValueError("max_queue_depth must be >= 0")
        if retry_after_seconds < 1:
            raise ValueError("retry_after_seconds must be >= 1")

        self.max_concurrent = max_concurrent
        self.max_queue_depth = max_queue_depth
        self.retry_after_seconds = retry_after_seconds
        self._lock = threading.Lock()
        self._active = 0
        self._waiting = 0
        self._slots = threading.Semaphore(max_concurrent)

    def snapshot(self) -> QueueSnapshot:
        """Return a thread-safe snapshot of queue counters."""
        with self._lock:
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> QueueSnapshot:
        return QueueSnapshot(
            active=self._active,
            waiting=self._waiting,
            max_concurrent=self.max_concurrent,
            max_queue_depth=self.max_queue_depth,
        )

    @contextmanager
    def slot(self) -> Iterator[QueueSnapshot]:
        """Acquire queue admission and an active slot for one RAG request.

        Yields:
            Queue state after the active slot has been acquired.

        Raises:
            QueueFullError: If the waiting queue is at capacity.
        """
        with self._lock:
            if self._active + self._waiting >= self.max_concurrent + self.max_queue_depth:
                raise QueueFullError(
                    self._snapshot_unlocked(),
                    retry_after_seconds=self.retry_after_seconds,
                )
            self._waiting += 1

        self._slots.acquire()
        try:
            with self._lock:
                self._waiting -= 1
                self._active += 1
                snap = self._snapshot_unlocked()
            yield snap
        finally:
            with self._lock:
                self._active -= 1
            self._slots.release()
