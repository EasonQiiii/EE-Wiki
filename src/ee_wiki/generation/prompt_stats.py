"""Prompt size helpers for generation diagnostics."""

from __future__ import annotations


def estimate_llm_tokens(text: str) -> int:
    """Estimate LLM token count for logging (not exact BPE).

    Uses a simple script mix heuristic tuned for Qwen-style BPE on
    Chinese-heavy engineering docs: CJK characters count roughly 1.2
    chars per token; Latin digits and punctuation roughly 4 chars per token.

    Args:
        text: Prompt or context string.

    Returns:
        Non-negative estimated token count.
    """
    if not text:
        return 0

    cjk = 0
    other = 0
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            cjk += 1
        else:
            other += 1

    return max(1, int(cjk / 1.2 + other / 4))


def prompt_size_fields(text: str) -> dict[str, int]:
    """Return prompt size fields for structured logging."""
    return {
        "prompt_chars": len(text),
        "prompt_tokens_est": estimate_llm_tokens(text),
    }
