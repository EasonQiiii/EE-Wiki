"""Client disconnect handling for streaming chat responses."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator

from starlette.requests import Request

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


async def watch_client_disconnect(
    request: Request,
    cancel: threading.Event,
    *,
    label: str,
) -> None:
    """Set ``cancel`` when the HTTP client closes the connection."""
    while not cancel.is_set():
        if await request.is_disconnected():
            cancel.set()
            logger.info("%s cancelled: client disconnected", label)
            return
        await asyncio.sleep(0.05)


async def iter_sync_text_chunks(
    chunks: Iterator[str],
    *,
    cancel: threading.Event,
    request: Request | None = None,
) -> AsyncIterator[str]:
    """Bridge a blocking text iterator to async SSE without blocking the event loop.

    Each ``next()`` call runs in a worker thread so disconnect watchers can run
    between MLX tokens.
    """
    iterator = iter(chunks)
    try:
        while not cancel.is_set():
            if request is not None and await request.is_disconnected():
                cancel.set()
                logger.info("Stopping stream: client disconnected during generation")
                break
            try:
                fragment = next(iterator)
            except StopIteration:
                break
            yield fragment
            await asyncio.sleep(0)
    finally:
        if cancel.is_set():
            iterator.close()
