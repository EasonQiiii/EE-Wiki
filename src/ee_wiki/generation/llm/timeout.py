"""Wall-clock timeout helpers for blocking LLM backends."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.llm.errors import LlmTimeoutError

logger = get_logger(__name__)

T = TypeVar("T")


def call_with_timeout(
    func: Callable[[], T],
    *,
    timeout_seconds: float | None,
    label: str,
) -> T:
    """Run ``func`` in a worker thread with an optional timeout.

    Args:
        func: Blocking callable to execute.
        timeout_seconds: Maximum seconds to wait, or ``None`` to disable.
        label: Human-readable label for logs and errors.

    Returns:
        The return value of ``func``.

    Raises:
        LlmTimeoutError: When ``timeout_seconds`` is exceeded.
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        return func()

    holder: list[T] = []
    error_holder: list[BaseException] = []

    def runner() -> None:
        try:
            holder.append(func())
        except BaseException as exc:  # noqa: BLE001 — propagate any backend failure
            error_holder.append(exc)

    thread = threading.Thread(target=runner, daemon=True, name=f"llm-timeout-{label}")
    thread.start()
    thread.join(timeout=timeout_seconds)
    if thread.is_alive():
        logger.error("%s exceeded %.1fs timeout", label, timeout_seconds)
        raise LlmTimeoutError(f"{label} exceeded {timeout_seconds:.0f}s")
    if error_holder:
        raise error_holder[0]
    return holder[0]


def check_stream_timeout(
    started: float,
    *,
    timeout_seconds: float | None,
    label: str,
) -> None:
    """Raise when a streaming generation exceeds its configured deadline.

    Args:
        started: ``time.monotonic()`` timestamp when generation began.
        timeout_seconds: Maximum seconds for the stream, or ``None`` to disable.
        label: Human-readable label for logs and errors.

    Raises:
        LlmTimeoutError: When the deadline is exceeded.
    """
    if timeout_seconds is None or timeout_seconds <= 0:
        return
    elapsed = time.monotonic() - started
    if elapsed > timeout_seconds:
        logger.error("%s exceeded %.1fs timeout after %.1fs", label, timeout_seconds, elapsed)
        raise LlmTimeoutError(f"{label} exceeded {timeout_seconds:.0f}s")
