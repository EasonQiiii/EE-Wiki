"""Request timeout helpers for RAG HTTP endpoints."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import TypeVar

from fastapi import HTTPException

from ee_wiki.api.stream_cancel import await_sync_iterator_next

REQUEST_TIMEOUT_MESSAGE = "请求超时，请重试"

T = TypeVar("T")


class RequestTimeoutError(Exception):
    """A RAG request exceeded the configured wall-clock limit."""


def raise_request_timeout_http_error(exc: Exception) -> HTTPException:
    """Map timeout errors to an HTTP 504 with a user-facing message."""
    return HTTPException(
        status_code=504,
        detail={
            "error": "request_timeout",
            "message": REQUEST_TIMEOUT_MESSAGE,
        },
    )


async def run_sync_with_request_timeout(
    func: Callable[..., T],
    /,
    *args: object,
    timeout_seconds: float | None,
    **kwargs: object,
) -> T:
    """Run a blocking callable with an optional asyncio wall-clock timeout.

    Args:
        func: Blocking function to execute in a worker thread.
        *args: Positional arguments for ``func``.
        timeout_seconds: Maximum seconds to wait, or ``None`` to disable.
        **kwargs: Keyword arguments for ``func``.

    Returns:
        The return value of ``func``.

    Raises:
        RequestTimeoutError: When ``timeout_seconds`` is exceeded.
        LlmTimeoutError: Propagated from ``func`` when LLM generation times out.
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        return await asyncio.to_thread(func, *args, **kwargs)

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout_seconds,
        )
    except TimeoutError as exc:
        raise RequestTimeoutError(
            f"Request exceeded {timeout_seconds}s timeout"
        ) from exc


async def iter_with_request_timeout(
    chunks: Iterator[str],
    *,
    timeout_seconds: float | None,
    cancel: object | None = None,
) -> AsyncIterator[str]:
    """Bridge a blocking text iterator to async with a wall-clock deadline.

    Args:
        chunks: Blocking text iterator (for example MLX token fragments).
        timeout_seconds: Maximum seconds for the full stream, or ``None`` to disable.
        cancel: Optional threading event checked between fragments.

    Yields:
        Text fragments from ``chunks``.

    Raises:
        RequestTimeoutError: When the deadline is exceeded before the stream ends.
        LlmTimeoutError: Propagated from ``chunks`` when LLM generation times out.
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        async for fragment in _iter_sync_chunks(chunks, cancel=cancel):
            yield fragment
        return

    deadline = time.monotonic() + timeout_seconds
    async for fragment in _iter_sync_chunks(chunks, cancel=cancel):
        if time.monotonic() > deadline:
            raise RequestTimeoutError(
                f"Request exceeded {timeout_seconds}s timeout during streaming"
            )
        yield fragment


async def _iter_sync_chunks(
    chunks: Iterator[str],
    *,
    cancel: object | None,
) -> AsyncIterator[str]:
    iterator = iter(chunks)
    try:
        while True:
            if cancel is not None and getattr(cancel, "is_set", lambda: False)():
                break
            try:
                fragment = await await_sync_iterator_next(iterator)
            except StopIteration:
                break
            if fragment is None:
                break
            yield fragment
            await asyncio.sleep(0)
    finally:
        if cancel is not None and getattr(cancel, "is_set", lambda: False)():
            iterator.close()


async def await_with_request_timeout(
    awaitable: Awaitable[T],
    *,
    timeout_seconds: float | None,
) -> T:
    """Await a coroutine with an optional wall-clock timeout.

    Args:
        awaitable: Coroutine or task to await.
        timeout_seconds: Maximum seconds to wait, or ``None`` to disable.

    Returns:
        The result of ``awaitable``.

    Raises:
        RequestTimeoutError: When ``timeout_seconds`` is exceeded.
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        return await awaitable

    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)
    except TimeoutError as exc:
        raise RequestTimeoutError(
            f"Request exceeded {timeout_seconds}s timeout"
        ) from exc
