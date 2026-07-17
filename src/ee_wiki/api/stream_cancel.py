"""Client disconnect handling for streaming chat responses."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor

from starlette.requests import Request

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

# MLX GPU streams are thread-local; all token ``next()`` calls must use one worker.
_LLM_STREAM_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="ee-wiki-llm-stream",
)


async def await_sync_iterator_next(iterator: Iterator[str]) -> str | None:
    """Advance a blocking text iterator on the dedicated LLM worker thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_LLM_STREAM_EXECUTOR, next, iterator, None)


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
    timeout_seconds: float | None = None,
) -> AsyncIterator[str]:
    """Bridge a blocking text iterator to async SSE without blocking the event loop.

    Each ``next()`` call runs in a worker thread so disconnect watchers can run
    between MLX tokens.

    Args:
        chunks: Blocking text iterator (for example MLX/local token fragments).
        cancel: Threading event set on client disconnect or explicit cancel.
        request: Optional request used to detect client disconnect.
        timeout_seconds: Optional wall-clock budget for the whole stream. When
            exceeded a :class:`RequestTimeoutError` is raised so the caller can
            map it to an HTTP 504 (previously the generation phase was unbounded).
    """
    from ee_wiki.api.timeout import RequestTimeoutError

    iterator = iter(chunks)
    deadline = (
        time.monotonic() + timeout_seconds
        if timeout_seconds and timeout_seconds > 0
        else None
    )
    try:
        while not cancel.is_set():
            if request is not None and await request.is_disconnected():
                cancel.set()
                logger.info("Stopping stream: client disconnected during generation")
                break
            if deadline is not None and time.monotonic() > deadline:
                raise RequestTimeoutError(
                    f"Request exceeded {timeout_seconds}s timeout during generation"
                )
            try:
                fragment = await await_sync_iterator_next(iterator)
            except StopIteration:
                break
            if fragment is None:
                break
            yield fragment
            await asyncio.sleep(0)
    finally:
        if cancel.is_set():
            iterator.close()
