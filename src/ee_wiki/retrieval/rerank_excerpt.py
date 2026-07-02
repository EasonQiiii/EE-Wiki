"""Query-focused excerpts for cross-encoder reranking."""

from __future__ import annotations

import re

from ee_wiki.retrieval.query_boost import query_boost_tokens


def query_focused_excerpt(
    content: str,
    query: str,
    *,
    max_len: int = 512,
) -> str:
    """Return a substring of ``content`` centered on query-relevant terms.

    Falls back to the leading ``max_len`` characters when no query term matches.

    Args:
        content: Full chunk text.
        query: User query used for term highlighting.
        max_len: Maximum excerpt length passed to the reranker.

    Returns:
        Excerpt string of at most ``max_len`` characters.
    """
    text = content.strip()
    if len(text) <= max_len:
        return text

    terms = query_boost_tokens(query)
    if not terms:
        return text[:max_len]

    upper = text.upper()
    best_index = -1
    best_score = 0
    for term in terms:
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        for match in pattern.finditer(text):
            start = match.start()
            window_start = max(0, start - max_len // 3)
            window = upper[window_start : window_start + max_len]
            score = sum(1 for token in terms if token.upper() in window)
            if score > best_score:
                best_score = score
                best_index = window_start

    if best_index < 0:
        return text[:max_len]
    return text[best_index : best_index + max_len]
