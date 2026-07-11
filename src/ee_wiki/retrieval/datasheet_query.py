"""Datasheet-specific query parsing and retrieval rank adjustments."""

from __future__ import annotations

import re
from dataclasses import dataclass

_FIGURE_REF = re.compile(r"\b(?:figure|fig\.?)\s*(\d+)\b", re.IGNORECASE)
_TABLE_REF = re.compile(r"\btable\s+(\d+)\b", re.IGNORECASE)
_EXPLICIT_PAGE_REF = re.compile(
    r"\b(?:page|pp?\.?|第)\s*(\d+)\b",
    re.IGNORECASE,
)
_PAGE_HEADING = re.compile(r"^##\s*Page\s+(\d+)\b", re.MULTILINE | re.IGNORECASE)
_NON_MULTIPLEXED = re.compile(r"\bnon[- ]multiplexed\b", re.IGNORECASE)
_MULTIPLEXED = re.compile(r"\bmultiplexed\b", re.IGNORECASE)

_FIGURE_HIT_BOOST = 12
_FIGURE_PAGE_CONFUSION_PENALTY = 10
_TABLE_HIT_BOOST = 10
_REQUIRED_PHRASE_BOOST = 6
_NEGATED_VARIANT_PENALTY = 8


@dataclass(frozen=True)
class DatasheetQueryHints:
    """Structured hints parsed from a natural-language datasheet query."""

    figure_numbers: tuple[int, ...] = ()
    table_numbers: tuple[int, ...] = ()
    explicit_page_numbers: tuple[int, ...] = ()
    required_phrases: tuple[str, ...] = ()
    negated_variants: tuple[tuple[str, str], ...] = ()


def parse_datasheet_query_hints(query: str) -> DatasheetQueryHints:
    """Extract Figure/Table/Page refs and negated modifiers from ``query``.

    Args:
        query: Raw user question.

    Returns:
        Hints used by retrieval rank adjustment and query expansion.
    """
    figure_numbers = tuple(int(match) for match in _FIGURE_REF.findall(query))
    table_numbers = tuple(int(match) for match in _TABLE_REF.findall(query))
    explicit_page_numbers = tuple(int(match) for match in _EXPLICIT_PAGE_REF.findall(query))

    required: list[str] = []
    negated: list[tuple[str, str]] = []
    if _NON_MULTIPLEXED.search(query):
        required.append("non-multiplexed")
        negated.append(("non-multiplexed", "multiplexed"))

    return DatasheetQueryHints(
        figure_numbers=figure_numbers,
        table_numbers=table_numbers,
        explicit_page_numbers=explicit_page_numbers,
        required_phrases=tuple(required),
        negated_variants=tuple(negated),
    )


def expand_datasheet_query_tokens(query: str, hints: DatasheetQueryHints | None = None) -> str:
    """Append explicit Figure/Table tokens to improve BM25 and dense recall.

    Args:
        query: Original user question.
        hints: Pre-parsed hints; computed when omitted.

    Returns:
        Query string, unchanged when no Figure/Table refs are present.
    """
    parsed = hints or parse_datasheet_query_hints(query)
    extras: list[str] = []
    for number in parsed.figure_numbers:
        extras.append(f"Figure {number}")
    for number in parsed.table_numbers:
        extras.append(f"Table {number}")
    if not extras:
        return query
    return f"{query} {' '.join(extras)}"


def datasheet_rank_adjustment(
    content: str,
    chunk_id: str,
    hints: DatasheetQueryHints,
) -> int:
    """Score adjustment for Figure/Page disambiguation and negated modifiers.

    Args:
        content: Chunk body text.
        chunk_id: Stable chunk identifier (may contain ``page-N`` segments).
        hints: Parsed query hints.

    Returns:
        Signed boost to add to hybrid keyword ranking (higher is better).
    """
    if not any(
        (
            hints.figure_numbers,
            hints.table_numbers,
            hints.required_phrases,
            hints.negated_variants,
        )
    ):
        return 0

    upper = content.upper()
    lowered_id = chunk_id.casefold()
    score = 0

    for number in hints.figure_numbers:
        label = f"FIGURE {number}"
        if label in upper:
            score += _FIGURE_HIT_BOOST
            continue
        if number not in hints.explicit_page_numbers:
            if f"__page-{number}__" in lowered_id or f"page-{number}-" in lowered_id:
                score -= _FIGURE_PAGE_CONFUSION_PENALTY
            elif _PAGE_HEADING.search(content) and f"PAGE {number}" in upper:
                score -= _FIGURE_PAGE_CONFUSION_PENALTY - 2

    for number in hints.table_numbers:
        if f"TABLE {number}" in upper:
            score += _TABLE_HIT_BOOST

    for phrase in hints.required_phrases:
        if phrase.upper() in upper:
            score += _REQUIRED_PHRASE_BOOST

    for required, forbidden in hints.negated_variants:
        if required.upper() not in upper and forbidden.upper() in upper:
            score -= _NEGATED_VARIANT_PENALTY

    return score
