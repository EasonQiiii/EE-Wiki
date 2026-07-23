"""Tests for Open WebUI streaming status helpers."""

from __future__ import annotations

import json

from ee_wiki.api.stream_status import (
    FA_AI_SUMMARY_STATUS,
    FA_ANALYZE_STATUS,
    FA_ATTACHMENT_ANALYZE_STATUS,
    FA_DOWNLOAD_STATUS,
    FA_EXTRACT_FAILS_STATUS,
    FA_FETCH_STATUS,
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


def test_fa_status_templates() -> None:
    assert FA_FETCH_STATUS == "正在拉取 Radar…"
    assert FA_ANALYZE_STATUS == "正在分析 FA 背景…"
    assert FA_EXTRACT_FAILS_STATUS == "正在提取 Fail items…"
    assert FA_AI_SUMMARY_STATUS == "正在生成 AI Summary…"
    assert FA_ATTACHMENT_ANALYZE_STATUS == "正在分析附件内容…"
    assert FA_DOWNLOAD_STATUS.format(done=2, total=5) == "正在下载附件 (2/5)…"
