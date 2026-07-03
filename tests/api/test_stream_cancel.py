"""Tests for streaming iterator bridge."""

from __future__ import annotations

import asyncio
import threading

from ee_wiki.api.stream_cancel import await_sync_iterator_next


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
