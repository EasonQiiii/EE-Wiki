"""Tests for streaming iterator bridge."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from ee_wiki.api.stream_cancel import await_sync_iterator_next, iter_sync_text_chunks
from ee_wiki.api.timeout import RequestTimeoutError


def test_await_sync_iterator_next_uses_single_worker_thread() -> None:
    thread_ids: list[int] = []

    def _chunks():
        for value in ("a", "b", "c"):
            thread_ids.append(threading.get_ident())
            yield value

    async def _collect() -> list[str]:
        iterator = _chunks()
        parts: list[str] = []
        while True:
            fragment = await await_sync_iterator_next(iterator)
            if fragment is None:
                break
            parts.append(fragment)
        return parts

    parts = asyncio.run(_collect())
    assert parts == ["a", "b", "c"]
    assert len(thread_ids) == 3
    assert len(set(thread_ids)) == 1


def test_iter_sync_text_chunks_raises_on_timeout() -> None:
    def _slow_chunks():
        yield "first"
        time.sleep(0.2)
        yield "second"

    async def _collect() -> None:
        cancel = threading.Event()
        with pytest.raises(RequestTimeoutError, match="during generation"):
            async for _ in iter_sync_text_chunks(
                _slow_chunks(),
                cancel=cancel,
                timeout_seconds=0.05,
            ):
                pass

    asyncio.run(_collect())
