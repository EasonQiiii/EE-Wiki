"""Query expansion for hardware and datasheet-specific recall."""

from __future__ import annotations

from ee_wiki.retrieval.datasheet_query import (
    expand_datasheet_query_tokens,
    parse_datasheet_query_hints,
)


def expand_hw_query(query: str) -> str:
    """Return an expanded query when datasheet Figure/Table refs need extra recall.

    Schematic evidence still comes from indexed OCR content; this hook only
    appends explicit Figure/Table tokens for BM25 and dense embedding recall.
    """
    hints = parse_datasheet_query_hints(query)
    return expand_datasheet_query_tokens(query, hints)
