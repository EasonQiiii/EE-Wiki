"""Format retrieved chunks into LLM context blocks."""

from __future__ import annotations

from ee_wiki.common.types import Citation
from ee_wiki.retrieval.hybrid.engine import HybridChunk
from ee_wiki.retrieval.rewrite import ConversationTurn, needs_answer_history

GLOBAL_SEGMENT = "global"
COMMON_SEGMENT = "common"

HISTORY_MAX_TURNS = 6
HISTORY_MAX_CHARS_PER_TURN = 4000


def knowledge_scope_tier(product: str, project: str, build: str) -> str:
    """Classify a chunk's knowledge layer for prompt headers.

    Args:
        product: Metadata product segment.
        project: Metadata project segment.
        build: Metadata build segment.

    Returns:
        ``global``, ``product_common``, ``project_common``, or ``build``.
    """
    if product == GLOBAL_SEGMENT:
        return "global"
    if project == COMMON_SEGMENT:
        return "product_common"
    if build == COMMON_SEGMENT:
        return "project_common"
    return "build"


def merge_agent_evidence_into_context(
    context: str,
    agent_evidence: str | None,
) -> str:
    """Prepend specialist ToolBus evidence ahead of retrieved chunks (ADR 0012).

    Args:
        context: Formatted retrieved context blocks (may be empty).
        agent_evidence: Optional fused specialist markdown from the supervisor.

    Returns:
        Context string for ``{{context}}``, with an evidence section when present.
    """
    evidence = (agent_evidence or "").strip()
    body = (context or "").strip()
    if not evidence:
        return body
    if not body:
        return f"## Agent tool evidence\n{evidence}"
    return (
        f"## Agent tool evidence\n{evidence}\n\n"
        f"## Retrieved context\n{body}"
    )


def format_context_blocks(
    chunks: list[HybridChunk],
    *,
    graph_enrichment: str | None = None,
) -> str:
    """Render chunks as numbered context blocks for prompt injection.

    Each block header includes scope tier, product, project, build, source, page,
    and chunk_id so the LLM can distinguish build facts from common and global
    knowledge. When ``graph_enrichment`` is provided (retrieval config-gated),
    it is appended after document blocks as a non-cited neighborhood summary.

    Args:
        chunks: Retrieved chunks with citation metadata.
        graph_enrichment: Optional compact graph neighborhood text from retrieval.

    Returns:
        Multi-block context string with ``[N]`` prefixes.
    """
    blocks: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        citation = chunk.citation
        product = str(chunk.metadata.get("product", ""))
        project = str(chunk.metadata.get("project", ""))
        build = str(chunk.metadata.get("build", ""))
        scope = knowledge_scope_tier(product, project, build)
        header = (
            f"[{index}] scope={scope} product={product} project={project} "
            f"build={build} "
            f"source={citation.get('source_file', '')} "
            f"page={citation.get('page', 0)} chunk_id={chunk.chunk_id}"
        )
        if chunk.heading_path:
            header = f"{header} section={chunk.heading_path}"
        blocks.append(f"{header}\n{chunk.content.strip()}")
    text = "\n\n".join(blocks)
    if graph_enrichment and graph_enrichment.strip():
        if text:
            text = f"{text}\n\n{graph_enrichment.strip()}"
        else:
            text = graph_enrichment.strip()
    return text


def resolve_history_for_prompt(
    question: str,
    history: list[ConversationTurn] | None,
    *,
    task: str | None = None,
    prepared_task: str | None = None,
    retrieval_query: str | None = None,
) -> str:
    """Render conversation history only when the question depends on prior turns.

    Args:
        question: Current user question.
        history: Prior conversation turns, if any.
        task: Resolved prompt task label, if known.
        prepared_task: Task label from merged prepare, if any.
        retrieval_query: Retrieval query after prepare/rewrite, if any.

    Returns:
        Formatted history block, or ``(none)`` when history should be omitted.
    """
    if history and needs_answer_history(
        question,
        history,
        task=task,
        prepared_task=prepared_task,
        retrieval_query=retrieval_query,
    ):
        return format_history_block(history)
    return format_history_block(None)


def format_history_block(
    history: list[ConversationTurn] | None,
    *,
    max_turns: int = HISTORY_MAX_TURNS,
    max_chars_per_turn: int = HISTORY_MAX_CHARS_PER_TURN,
) -> str:
    """Render prior conversation turns for the ``{{history}}`` prompt placeholder.

    Keeps the most recent ``max_turns`` turns so follow-up requests such as
    "translate the above answer to English" can see the previous answer verbatim.

    Args:
        history: Prior conversation turns, oldest first (may be None or empty).
        max_turns: Maximum number of recent turns to include.
        max_chars_per_turn: Truncation limit per turn to bound prompt size.

    Returns:
        Formatted history text, or a placeholder line when there is no history.
    """
    if not history:
        return "(none)"
    recent = history[-max_turns:]
    lines: list[str] = []
    for turn in recent:
        role_label = "User" if turn.role == "user" else "Assistant"
        content = turn.content.strip()
        if len(content) > max_chars_per_turn:
            content = content[:max_chars_per_turn] + "…(truncated)"
        lines.append(f"[{role_label}]:\n{content}")
    return "\n\n".join(lines)


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
