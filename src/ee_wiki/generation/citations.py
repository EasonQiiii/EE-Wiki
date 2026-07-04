"""Build enriched citations from retrieved chunks."""

from __future__ import annotations

from ee_wiki.common.config import AppConfig
from ee_wiki.common.types import Citation
from ee_wiki.generation.citation_urls import (
    citation_image_urls,
    page_image_url,
    source_document_url,
)
from ee_wiki.retrieval.hybrid.engine import HybridChunk


def build_enriched_citations(chunks: list[HybridChunk], config: AppConfig) -> list[Citation]:
    """Convert retrieved chunks to citations with source URLs and image links.

    Args:
        chunks: Retrieved hybrid chunks used for generation.
        config: Application configuration (processed paths and public base URL).

    Returns:
        Citations aligned with context block numbering.
    """
    citations: list[Citation] = []
    for chunk in chunks:
        citation = chunk.citation
        target_file = str(chunk.metadata.get("target_file") or "")
        if not target_file:
            source = str(citation.get("source_file", ""))
            if source.startswith("data/raw/"):
                target_file = source.replace("data/raw/", "data/processed/", 1)
            else:
                target_file = source

        chunk_id = str(citation.get("chunk_id", chunk.chunk_id))
        url = (
            source_document_url(config, target_file=target_file, chunk_id=chunk_id)
            if target_file
            else ""
        )
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
