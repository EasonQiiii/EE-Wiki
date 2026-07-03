"""Client-cancel helpers for blocking RAG work."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import TypeVar

from starlette.requests import Request

from ee_wiki.api.stream_cancel import watch_client_disconnect
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class ClientCancelledError(Exception):
    """The HTTP client disconnected before the RAG request finished."""


async def run_sync_until_cancel(
    func: Callable[..., T],
    /,
    *args: object,
    cancel: threading.Event,
    request: Request | None = None,
    label: str,
    poll_interval: float = 0.05,
    **kwargs: object,
) -> T:
    """Run a blocking callable in a worker thread, aborting when ``cancel`` is set.

    The worker thread may continue briefly after cancellation (for example while
    MLX finishes the current token), but the asyncio caller returns immediately.

    Args:
        func: Blocking function to execute.
        *args: Positional arguments for ``func``.
        cancel: Set when the client disconnects or the caller wants to abort.
        request: Optional request used to detect disconnects while waiting.
        label: Human-readable label for logs.
        poll_interval: Seconds between cancel checks while waiting.
        **kwargs: Keyword arguments for ``func``.

    Returns:
        The return value of ``func``.

    Raises:
        ClientCancelledError: When ``cancel`` is set before ``func`` completes.
    """
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        while not task.done():
            if cancel.is_set() or (
                request is not None and await request.is_disconnected()
            ):
                cancel.set()
                logger.info("%s cancelled: client disconnected", label)
                raise ClientCancelledError(f"{label} cancelled")
            await asyncio.sleep(poll_interval)
        return await task
    except asyncio.CancelledError:
        if cancel.is_set():
            raise ClientCancelledError(f"{label} cancelled") from None
        raise


def start_disconnect_watcher(
    request: Request,
    cancel: threading.Event,
    *,
    label: str,
) -> asyncio.Task[None]:
    """Start a background task that sets ``cancel`` when the client disconnects."""
    return asyncio.create_task(watch_client_disconnect(request, cancel, label=label))
