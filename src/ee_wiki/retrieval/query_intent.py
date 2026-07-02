"""Lightweight query intent hints for retrieval ranking (no signal alias tables)."""

from __future__ import annotations

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
