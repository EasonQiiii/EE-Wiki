"""Merge sibling chunks from the same logical document section at retrieval time."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ee_wiki.retrieval.hybrid.engine import HybridChunk

_SECTION_WINDOW_SUFFIX = re.compile(r"__w\d+$")


def section_key(chunk_id: str) -> str:
    """Return the stable section identifier for a chunk.

    Windowed sections append ``__w01``, ``__w02``, …; those suffixes are
    stripped so siblings from the same heading block group together.
    """
    return _SECTION_WINDOW_SUFFIX.sub("", chunk_id)


def build_section_index(chunks: list[Any]) -> dict[str, list[Any]]:
    """Index chunks by :func:`section_key`, preserving document order."""
    index: dict[str, list[Any]] = {}
    for chunk in chunks:
        key = section_key(chunk.chunk_id)
        index.setdefault(key, []).append(chunk)
    for siblings in index.values():
        siblings.sort(key=lambda item: item.chunk_id)
    return index


def merge_section_chunks(chunks: list[Any]) -> Any:
    """Combine ordered sibling chunks into one context block."""
    from ee_wiki.retrieval.hybrid.engine import HybridChunk

    first = chunks[0]
    merged_content = "\n\n".join(
        piece.content.strip() for piece in chunks if piece.content.strip()
    )
    excerpt = merged_content[:200].rstrip()
    if len(merged_content) > 200:
        excerpt += "…"
    return HybridChunk(
        chunk_id=section_key(first.chunk_id),
        content=merged_content,
        metadata=first.metadata,
        citation={
            **first.citation,
            "chunk_id": section_key(first.chunk_id),
            "excerpt": excerpt,
        },
        embedding=None,
    )


def expand_retrieved_sections(
    hits: list[Any],
    section_index: dict[str, list[Any]],
) -> list[Any]:
    """Replace hit fragments with full section content for generation.

    Args:
        hits: Ranked retrieval hits (already truncated to ``top_k_final``).
        section_index: Chunk lookup keyed by :func:`section_key`.

    Returns:
        De-duplicated list where each section appears once with merged text.
    """
    expanded: list[Any] = []
    seen: set[str] = set()
    for hit in hits:
        key = section_key(hit.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        siblings = section_index.get(key, [hit])
        if len(siblings) == 1:
            expanded.append(siblings[0])
        else:
            expanded.append(merge_section_chunks(siblings))
    return expanded
