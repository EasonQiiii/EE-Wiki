"""Build enriched citations from retrieved chunks."""

from __future__ import annotations

import re

from ee_wiki.common.config import AppConfig
from ee_wiki.common.types import Citation
from ee_wiki.generation.citation_urls import (
    citation_image_urls,
    page_image_url,
    raw_document_url,
)
from ee_wiki.retrieval.hybrid.engine import HybridChunk

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


def compact_citations(
    citations: list[Citation],
) -> tuple[list[Citation], dict[int, int]]:
    """Collapse duplicate citations (same ``source_file``) into one per document.

    Retrieval frequently returns several chunks from the same source document.
    Open WebUI collapses ``sources`` entries that share a URL and renumbers the
    ``[N]`` chips, which otherwise desynchronises the citation markers the LLM
    wrote (it cites by dense context-block index) from the surviving source
    entries — clicking ``[2]`` can then open the wrong document.

    Returns the de-duplicated citation list (first-appearance order) and a map
    from the dense context-block index to the compact source index, so callers
    can rewrite the answer text's ``[N]`` markers to stay 1:1 with ``sources``.
    """
    unique: list[Citation] = []
    seen: dict[str, int] = {}
    mapping: dict[int, int] = {}
    for dense_index, citation in enumerate(citations, start=1):
        key = citation.source_file
        compact_index = seen.get(key)
        if compact_index is None:
            compact_index = len(unique) + 1
            seen[key] = compact_index
            unique.append(citation)
        mapping[dense_index] = compact_index
    return unique, mapping


def remap_citation_markers(text: str, mapping: dict[int, int]) -> str:
    """Rewrite ``[N]`` citation markers using a dense->compact index map."""
    if not mapping:
        return text

    def _sub(match: re.Match[str]) -> str:
        dense = int(match.group(1))
        compact = mapping.get(dense)
        return f"[{compact}]" if compact is not None else match.group(0)

    return _CITATION_MARKER_RE.sub(_sub, text)


class StreamingCitationMarkerRemapper:
    """Stateful remapper for streamed answer text.

    Citation markers can straddle two streamed fragments (e.g. ``[3`` then
    ``]``); this buffers an incomplete trailing marker so it is remapped once
    the closing ``]`` arrives.
    """

    def __init__(self, mapping: dict[int, int]) -> None:
        self._mapping = mapping
        self._carry = ""

    def feed(self, chunk: str) -> str:
        if not self._mapping:
            return chunk
        data = self._carry + chunk
        tail = re.search(r"\[(\d*)$", data)
        if tail:
            self._carry = data[tail.start():]
            data = data[: tail.start()]
        else:
            self._carry = ""
        return remap_citation_markers(data, self._mapping)

    def finish(self) -> str:
        if not self._carry:
            return ""
        flushed = self._carry
        self._carry = ""
        return remap_citation_markers(flushed, self._mapping)


def build_enriched_citations(chunks: list[HybridChunk], config: AppConfig) -> list[Citation]:
    """Convert retrieved chunks to citations with source URLs and image links.

    Args:
        chunks: Retrieved hybrid chunks used for generation.
        config: Application configuration (processed/raw paths and public base URL).

    Returns:
        Citations aligned with context block numbering.
    """
    citations: list[Citation] = []
    for chunk in chunks:
        citation = chunk.citation
        source_file = str(citation.get("source_file", ""))
        target_file = str(chunk.metadata.get("target_file") or "")
        if not target_file and source_file.startswith("data/raw/"):
            target_file = source_file.replace("data/raw/", "data/processed/", 1)

        chunk_id = str(citation.get("chunk_id", chunk.chunk_id))
        url = raw_document_url(config, source_file=source_file) if source_file else ""
        images = citation_image_urls(config, target_file=target_file, content=chunk.content)
        if not images:
            page = int(citation.get("page", 0))
            page_url = page_image_url(config, target_file=target_file, page=page)
            if page_url:
                images = (page_url,)
        citations.append(
            Citation(
                source_file=str(citation.get("source_file", "")),
                chunk_id=chunk_id,
                page=int(citation.get("page", 0)),
                excerpt=str(citation.get("excerpt", "")),
                url=url,
                images=images,
            )
        )
    return citations
