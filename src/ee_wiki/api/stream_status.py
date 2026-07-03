"""Open WebUI-compatible streaming status events for RAG progress."""

from __future__ import annotations

import json

RETRIEVAL_STATUS = "检索中…"
GENERATION_STATUS = "生成中…"


def clear_stream_status_sse(*, description: str = "") -> str:
    """Hide the active status indicator above the assistant message."""
    return format_stream_status_sse(description=description, done=True, hidden=True)


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


def format_stream_status_sse(
    *,
    description: str,
    done: bool = False,
    hidden: bool = False,
) -> str:
    """Format a Server-Sent Events line for a retrieval/progress status.

    Open WebUI forwards ``event`` payloads from chat completion streams to its
    status area above the assistant message.

    Args:
        description: Human-readable status text.
        done: When ``False``, the UI shows a loading shimmer.
        hidden: When ``True`` with ``done=True``, the status is auto-hidden.

    Returns:
        A complete ``data: ...\\n\\n`` SSE frame.
    """
    payload = {
        "event": format_stream_status_event(
            description=description,
            done=done,
            hidden=hidden,
        )
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
