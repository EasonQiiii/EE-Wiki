"""Request-scoped streaming status emitter for sync FA / Radar work.

Sync code paths (check-in, attachment materialize) run in worker threads while
``_stream_answer`` polls :func:`drain_stream_status_updates` and yields Open
WebUI status chunks.  Bind once per fetch via :func:`bind_stream_status_emitter`.
"""

from __future__ import annotations

import queue
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

_emitter: ContextVar[Callable[[str], None] | None] = ContextVar(
    "stream_status_emitter",
    default=None,
)


def push_stream_status(description: str) -> None:
    """Emit a status line when a streaming status hub is bound."""
    emitter = _emitter.get()
    if emitter is not None:
        emitter(description)


@contextmanager
def bind_stream_status_emitter(
    emitter: Callable[[str], None] | None,
) -> Iterator[None]:
    """Bind ``emitter`` for the current context (including worker threads)."""
    token: Token = _emitter.set(emitter)
    try:
        yield
    finally:
        _emitter.reset(token)


class StreamStatusHub:
    """Collects status descriptions from sync worker threads for SSE polling."""

    def __init__(self) -> None:
        self._queue: queue.SimpleQueue[str] = queue.SimpleQueue()

    def emit(self, description: str) -> None:
        """Record one status update (thread-safe)."""
        self._queue.put(description)

    def drain(self) -> list[str]:
        """Return and remove all pending status updates."""
        out: list[str] = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out


def drain_stream_status_updates(hub: StreamStatusHub) -> list[str]:
    """Return pending status lines from ``hub`` (convenience alias)."""
    return hub.drain()
