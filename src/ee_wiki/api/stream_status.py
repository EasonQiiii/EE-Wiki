"""Open WebUI-compatible streaming status events for RAG progress.

Status events are embedded inside standard OpenAI chat completion chunk
payloads so Open WebUI's SSE parser recognises them (it ignores bare frames
without ``id`` / ``object`` / ``choices``).
"""

from __future__ import annotations

import json

RETRIEVAL_STATUS = "检索中…"
GENERATION_STATUS = "生成中…"

# FA / Radar-specific phases (Problem 1: give the UI a real status instead of a
# generic "检索中" while the backend talks to Radar / downloads attachments).
FA_FETCH_STATUS = "正在拉取 Radar 票…"
# Check-in LLM face read-through (title / description / diagnosis → briefing).
FA_ANALYZE_STATUS = "正在分析 FA 背景…"
# User asked to analyze a named log / attachment body (after materialize).
FA_ATTACHMENT_ANALYZE_STATUS = "正在分析附件内容…"
# Progress template for on-demand attachment downloads: "正在下载附件 (3/10)…".
FA_DOWNLOAD_STATUS = "正在下载附件 ({done}/{total})…"


def format_stream_status_event(
    *,
    description: str,
    done: bool = False,
    hidden: bool = False,
) -> dict[str, object]:
    """Build an Open WebUI ``status`` event payload.

    Args:
        description: Human-readable status text (supports markdown).
        done: When ``False``, the UI shows a loading shimmer.
        hidden: When ``True`` with ``done=True``, the status is auto-hidden.

    Returns:
        Event object suitable for the ``event`` field on an SSE chunk.
    """
    return {
        "type": "status",
        "data": {
            "description": description,
            "done": done,
            "hidden": hidden,
        },
    }


def format_status_chunk(
    *,
    chat_id: str,
    model: str,
    created: int,
    description: str,
    done: bool = False,
    hidden: bool = False,
) -> str:
    """Format a status event as a standard chat completion SSE chunk.

    Open WebUI only processes SSE frames shaped like OpenAI chat completion
    chunks (with ``id``, ``object``, ``choices``).  Embedding the status
    ``event`` inside such a chunk ensures the UI renders the indicator
    immediately.

    Args:
        chat_id: The chat completion ID for this stream.
        model: Model name echoed back in the chunk.
        created: Unix timestamp for the stream.
        description: Human-readable status text.
        done: When ``False``, the UI shows a loading shimmer.
        hidden: When ``True`` with ``done=True``, the status is auto-hidden.

    Returns:
        A complete ``data: ...\\n\\n`` SSE frame.
    """
    payload: dict[str, object] = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": None}],
        "event": format_stream_status_event(
            description=description,
            done=done,
            hidden=hidden,
        ),
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def clear_status_chunk(
    *,
    chat_id: str,
    model: str,
    created: int,
    description: str = "",
) -> str:
    """Hide the active status indicator above the assistant message.

    Args:
        chat_id: The chat completion ID for this stream.
        model: Model name echoed back in the chunk.
        created: Unix timestamp for the stream.
        description: Optional label shown briefly before hiding.

    Returns:
        A complete ``data: ...\\n\\n`` SSE frame that clears the status.
    """
    return format_status_chunk(
        chat_id=chat_id,
        model=model,
        created=created,
        description=description,
        done=True,
        hidden=True,
    )


# --- Legacy helpers (kept for non-streaming / test callers) ---


def clear_stream_status_sse(*, description: str = "") -> str:
    """Hide the active status indicator (legacy bare-frame format)."""
    return format_stream_status_sse(description=description, done=True, hidden=True)


def format_stream_status_sse(
    *,
    description: str,
    done: bool = False,
    hidden: bool = False,
) -> str:
    """Format a bare status SSE frame (legacy, not recognised by Open WebUI).

    Prefer :func:`format_status_chunk` for streaming chat completions.
    """
    payload = {
        "event": format_stream_status_event(
            description=description,
            done=done,
            hidden=hidden,
        )
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
