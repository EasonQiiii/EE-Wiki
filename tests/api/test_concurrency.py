"""Tests for RAG request queue gate."""

from __future__ import annotations

import threading
import time

import pytest

from ee_wiki.api.concurrency import QueueFullError, RequestQueueGate


def test_slot_allows_up_to_capacity() -> None:
    gate = RequestQueueGate(max_concurrent=1, max_queue_depth=1, retry_after_seconds=10)
    release = threading.Event()
    started = threading.Event()

    def worker() -> None:
        with gate.slot():
            started.set()
            release.wait(timeout=2)

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert started.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    snap = gate.snapshot()
    assert snap.active == 1
    assert snap.waiting == 1
    release.set()
    first.join(timeout=2)
    second.join(timeout=2)


def test_slot_rejects_when_queue_is_full() -> None:
    gate = RequestQueueGate(max_concurrent=1, max_queue_depth=0, retry_after_seconds=12)
    release = threading.Event()
    entered = threading.Event()

    def hold_slot() -> None:
        with gate.slot():
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=hold_slot)
    thread.start()
    assert entered.wait(timeout=2)

    with pytest.raises(QueueFullError) as exc_info:
        with gate.slot():
            pass

    assert exc_info.value.retry_after_seconds == 12
    assert exc_info.value.snapshot.active == 1
    assert exc_info.value.snapshot.waiting == 0
    assert exc_info.value.snapshot.capacity_remaining == 0
    release.set()
    thread.join(timeout=2)


def test_snapshot_tracks_capacity_remaining() -> None:
    gate = RequestQueueGate(max_concurrent=2, max_queue_depth=2, retry_after_seconds=5)
    snap = gate.snapshot()
    assert snap.capacity == 4
    assert snap.capacity_remaining == 4
