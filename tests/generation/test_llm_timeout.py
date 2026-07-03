"""Tests for LLM backend timeout helpers."""

from __future__ import annotations

import time

import pytest

from ee_wiki.generation.llm.errors import LlmTimeoutError
from ee_wiki.generation.llm.timeout import call_with_timeout, check_stream_timeout


def test_call_with_timeout_returns_result_when_fast() -> None:
    assert call_with_timeout(lambda: "ok", timeout_seconds=1.0, label="test") == "ok"


def test_call_with_timeout_raises_when_slow() -> None:
    def slow() -> str:
        time.sleep(0.2)
        return "late"

    with pytest.raises(LlmTimeoutError, match="exceeded"):
        call_with_timeout(slow, timeout_seconds=0.05, label="slow test")


def test_check_stream_timeout_raises_after_deadline() -> None:
    started = time.monotonic() - 2.0
    with pytest.raises(LlmTimeoutError, match="exceeded"):
        check_stream_timeout(started, timeout_seconds=1.0, label="stream test")
