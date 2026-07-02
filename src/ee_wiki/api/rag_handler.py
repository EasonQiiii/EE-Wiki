"""Shared RAG route helpers for queue admission and response headers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from fastapi import HTTPException

from ee_wiki.api.concurrency import (
    QueueFullError,
    QueueSnapshot,
    queue_response_headers,
)

if TYPE_CHECKING:
    from ee_wiki.api.concurrency import RequestQueueGate


def raise_queue_full_http_error(exc: QueueFullError) -> HTTPException:
    """Map a queue-full error to an HTTP 503 with queue visibility headers."""
    return HTTPException(
        status_code=503,
        detail={
            "error": "queue_full",
            "message": str(exc),
            "queue": {
                "active": exc.snapshot.active,
                "waiting": exc.snapshot.waiting,
                "max_concurrent": exc.snapshot.max_concurrent,
                "max_queue_depth": exc.snapshot.max_queue_depth,
                "capacity_remaining": exc.snapshot.capacity_remaining,
            },
            "retry_after_seconds": exc.retry_after_seconds,
        },
        headers=queue_response_headers(
            exc.snapshot,
            retry_after_seconds=exc.retry_after_seconds,
        ),
    )


@contextmanager
def rag_request_slot(gate: RequestQueueGate) -> Iterator[QueueSnapshot]:
    """Acquire a queue slot or raise HTTP 503 when the queue is full."""
    try:
        with gate.slot() as snapshot:
            yield snapshot
    except QueueFullError as exc:
        raise raise_queue_full_http_error(exc) from exc
