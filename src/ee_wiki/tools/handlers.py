"""Read-only engineering tool handlers backed by hybrid retrieval."""

from __future__ import annotations

from ee_wiki.common.serialization import DATASHEET_DOCUMENT_TYPE, SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.tools.context import ToolContext
from ee_wiki.tools.format import format_component_search, format_retrieval_result


def search_component(
    ctx: ToolContext,
    query: str,
    *,
    project: str | None = None,
    build: str | None = None,
    limit: int = 20,
) -> str:
    """Look up a schematic designator or part number in the component index.

    Args:
        ctx: Initialized tool context.
        query: Part number (for example ``STM32F407VGT6``) or designator (for example ``U101``).
        project: Optional project filter (for example ``logan``).
        build: Optional build filter (for example ``p1``).
        limit: Maximum number of hits to return.

    Returns:
        JSON text with matching component hits and scope labels.
    """
    hits = ctx.engine.search_components(
        query,
        target_project=project,
        target_build=build,
        limit=limit,
    )
    return format_component_search(query=query, hits=hits, layout=ctx.config.data_layout)


def query_schematic(
    ctx: ToolContext,
    query: str,
    *,
    project: str | None = None,
    build: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve schematic chunks relevant to an engineering question.

    Args:
        ctx: Initialized tool context.
        query: Natural language or keyword query about schematic content.
        project: Optional project filter.
        build: Optional build filter.
        top_k: Optional reranked result count override.

    Returns:
        JSON text with ranked schematic chunks and citations.
    """
    result = ctx.engine.retrieve(
        query,
        target_project=project,
        target_build=build,
        document_type=SCHEMATIC_DOCUMENT_TYPE,
        top_k_final=top_k,
    )
    return format_retrieval_result(
        query=query,
        result=result,
        layout=ctx.config.data_layout,
        document_type=SCHEMATIC_DOCUMENT_TYPE,
    )


def search_datasheet(
    ctx: ToolContext,
    query: str,
    *,
    project: str | None = None,
    build: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve datasheet chunks relevant to a component or electrical spec question.

    Args:
        ctx: Initialized tool context.
        query: Natural language or keyword query about datasheet content.
        project: Optional project filter.
        build: Optional build filter.
        top_k: Optional reranked result count override.

    Returns:
        JSON text with ranked datasheet chunks and citations.
    """
    result = ctx.engine.retrieve(
        query,
        target_project=project,
        target_build=build,
        document_type=DATASHEET_DOCUMENT_TYPE,
        top_k_final=top_k,
    )
    return format_retrieval_result(
        query=query,
        result=result,
        layout=ctx.config.data_layout,
        document_type=DATASHEET_DOCUMENT_TYPE,
    )


def engineering_search(
    ctx: ToolContext,
    query: str,
    *,
    project: str | None = None,
    build: str | None = None,
    document_type: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve ranked knowledge chunks across the configured scope.

    Args:
        ctx: Initialized tool context.
        query: Natural language or keyword engineering question.
        project: Optional project filter.
        build: Optional build filter.
        document_type: Optional document type filter (for example ``schematic``).
        top_k: Optional reranked result count override.

    Returns:
        JSON text with ranked chunks, scope labels, and citations.
    """
    result = ctx.engine.retrieve(
        query,
        target_project=project,
        target_build=build,
        document_type=document_type,
        top_k_final=top_k,
    )
    return format_retrieval_result(
        query=query,
        result=result,
        layout=ctx.config.data_layout,
        document_type=document_type,
    )
