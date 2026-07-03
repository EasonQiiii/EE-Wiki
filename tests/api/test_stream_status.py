"""Tests for Open WebUI streaming status helpers."""

from __future__ import annotations

import json

from ee_wiki.api.stream_status import (
    GENERATION_STATUS,
    RETRIEVAL_STATUS,
    clear_stream_status_sse,
    format_stream_status_event,
    format_stream_status_sse,
)


def test_format_stream_status_event_shape() -> None:
    event = format_stream_status_event(description=RETRIEVAL_STATUS, done=False, hidden=False)
    assert event == {
        "type": "status",
        "data": {
            "description": RETRIEVAL_STATUS,
            "done": False,
            "hidden": False,
        },
    }


def test_format_stream_status_sse_wraps_event() -> None:
    frame = format_stream_status_sse(description=RETRIEVAL_STATUS, done=True, hidden=True)
    assert frame.startswith("data: ")
    assert frame.endswith("\n\n")
    payload = json.loads(frame.removeprefix("data: ").strip())
    assert payload["event"]["type"] == "status"
    assert payload["event"]["data"]["description"] == RETRIEVAL_STATUS
    assert payload["event"]["data"]["done"] is True
    assert payload["event"]["data"]["hidden"] is True


def test_clear_stream_status_sse_hides_indicator() -> None:
    frame = clear_stream_status_sse(description=GENERATION_STATUS)
    payload = json.loads(frame.removeprefix("data: ").strip())
    assert payload["event"]["data"]["done"] is True
    assert payload["event"]["data"]["hidden"] is True
