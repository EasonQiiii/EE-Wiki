"""Format retrieved chunks into LLM context blocks."""

from __future__ import annotations

from ee_wiki.common.types import Citation
from ee_wiki.retrieval.hybrid.engine import HybridChunk

ENTERPRISE_PROJECT = "global"
PROJECT_SHARED_BUILD = "common"


def knowledge_scope_tier(project: str, build: str) -> str:
    """Classify a chunk's knowledge layer for prompt headers.

    Args:
        project: Metadata project segment.
        build: Metadata build segment.

    Returns:
        ``global``, ``project_common``, or ``build``.
    """
    if project == ENTERPRISE_PROJECT and build == ENTERPRISE_PROJECT:
        return "global"
    if build == PROJECT_SHARED_BUILD:
        return "project_common"
    return "build"


def format_context_blocks(chunks: list[HybridChunk]) -> str:
    """Render chunks as numbered context blocks for prompt injection.

    Each block header includes scope tier, project, build, source, page, and chunk_id
    so the LLM can distinguish build facts from project-common and global knowledge.

    Args:
        chunks: Retrieved chunks with citation metadata.

    Returns:
        Multi-block context string with ``[N]`` prefixes.
    """
    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        citation = chunk.citation
        project = str(chunk.metadata.get("project", ""))
        build = str(chunk.metadata.get("build", ""))
        scope = knowledge_scope_tier(project, build)
        header = (
            f"[{index}] scope={scope} project={project} build={build} "
            f"source={citation.get('source_file', '')} "
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
