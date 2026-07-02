"""Keyword boosts derived from the user query only."""

from __future__ import annotations

import re

from ee_wiki.retrieval.tokenizer import tokenize_hw_text

_MIN_TOKEN_LEN = 2
_SKIP_TOKENS = frozenset({"的", "有", "哪", "几", "组", "是", "在", "和", "与", "及", "pin", "pins", "signal", "signals"})


def query_boost_tokens(query: str) -> list[str]:
    """Return query terms that should rank literal chunk matches higher.

    Uses hardware-aware tokenization on the original query. No synonym tables
    or signal alias configuration.
    """
    try:
        raw_tokens = tokenize_hw_text(query)
    except ImportError:
        raw_tokens = re.findall(r"[A-Za-z0-9_&]+|[\u4e00-\u9fff]+", query)

    seen: set[str] = set()
    ordered: list[str] = []
    for token in raw_tokens:
        cleaned = token.strip()
        if len(cleaned) < _MIN_TOKEN_LEN:
            continue
        if cleaned.casefold() in _SKIP_TOKENS:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered
