"""Wall-clock phase timing footer for chat answers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RagPhaseTiming:
    """Monotonic timings for one RAG chat completion."""

    retrieval_seconds: float
    generation_seconds: float
    first_char_seconds: float


def _format_seconds(seconds: float) -> str:
    """Format one duration label for the footer."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.1f} 秒"
    minutes = int(seconds // 60)
    remainder = seconds % 60
    return f"{minutes} 分 {remainder:.1f} 秒"


def format_phase_timing_footer(timing: RagPhaseTiming) -> str:
    """Format retrieval / generation / first-char phase timings.

    Args:
        timing: Phase durations where ``generation_seconds`` is LLM prefill
            until the first streamed character, and ``first_char_seconds`` is
            end-to-end time until that character reaches the client.

    Returns:
        Markdown snippet appended after the assistant answer body.
    """
    retrieval = _format_seconds(timing.retrieval_seconds)
    generation = _format_seconds(timing.generation_seconds)
    first_char = _format_seconds(timing.first_char_seconds)
    return (
        f"\n\n---\n⏱ 检索 {retrieval} · 生成 {generation} · 首字 {first_char}"
    )
