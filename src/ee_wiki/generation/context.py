"""Format retrieved chunks into LLM context blocks."""

from __future__ import annotations

from ee_wiki.common.types import Citation
from ee_wiki.retrieval.hybrid.engine import HybridChunk


def format_context_blocks(chunks: list[HybridChunk]) -> str:
    """Render chunks as numbered context blocks for prompt injection.

    Args:
        chunks: Retrieved chunks with citation metadata.

    Returns:
        Multi-block context string with ``[N]`` prefixes.
    """
    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        citation = chunk.citation
        header = (
            f"[{index}] source={citation.get('source_file', '')} "
            f"page={citation.get('page', 0)} chunk_id={chunk.chunk_id}"
        )
        blocks.append(f"{header}\n{chunk.content.strip()}")
    return "\n\n".join(blocks)


def chunks_to_citations(chunks: list[HybridChunk]) -> list[Citation]:
    """Convert retrieved hybrid chunks to citation objects.

    Args:
        chunks: Retrieved chunks.

    Returns:
        Citation list aligned with context block numbering.
    """
    citations: list[Citation] = []
    for chunk in chunks:
        citation = chunk.citation
        citations.append(
            Citation(
                source_file=str(citation.get("source_file", "")),
                chunk_id=str(citation.get("chunk_id", chunk.chunk_id)),
                page=int(citation.get("page", 0)),
                excerpt=str(citation.get("excerpt", "")),
            )
        )
    return citations
