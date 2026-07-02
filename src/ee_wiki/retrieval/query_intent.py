"""Lightweight query intent hints for retrieval ranking (no signal alias tables)."""

from __future__ import annotations

from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE

_SCHEMATIC_SOURCE_MARKERS = (
    "pin",
    "pins",
    "信号",
    "引脚",
    "接口",
    "connector",
    "net",
    "网络",
    "原理图",
    "schematic",
    "sch",
)


def prefers_schematic_sources(query: str) -> bool:
    """Return whether the query is likely about schematic pin/signal evidence."""
    lower = query.casefold()
    return any(marker in lower for marker in _SCHEMATIC_SOURCE_MARKERS)


def effective_document_type(
    query: str,
    document_type: str | None,
) -> str | None:
    """Apply schematic intent when the caller did not set ``document_type``.

    Pin/signal queries default to schematic sources so engineering notes do
    not pollute hardware evidence retrieval.
    """
    if document_type is not None:
        return document_type
    if prefers_schematic_sources(query):
        return SCHEMATIC_DOCUMENT_TYPE
    return None
