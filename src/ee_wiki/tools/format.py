"""Serialize tool results for MCP and function-calling clients."""

from __future__ import annotations

import json
from typing import Any

from ee_wiki.knowledge.indexer.case_index import DebugCaseRecord
from ee_wiki.knowledge.indexer.component_index import ComponentHit
from ee_wiki.retrieval.hybrid.engine import HybridChunk, RetrievalResult

DEFAULT_CONTENT_PREVIEW_CHARS = 800


def _scope_label(*, project: str, build: str, layout) -> str:
    """Return a human-readable knowledge layer label for a hit."""
    if project == layout.enterprise_project and build == layout.enterprise_project:
        return "global"
    if build == layout.project_shared_build:
        return "common"
    return "build"


def component_hit_to_dict(hit: ComponentHit, *, layout) -> dict[str, Any]:
    """Convert one component lookup hit to a JSON-serializable mapping."""
    return {
        "key": hit.key,
        "kind": hit.kind,
        "chunk_id": hit.chunk_id,
        "project": hit.project,
        "build": hit.build,
        "scope": _scope_label(project=hit.project, build=hit.build, layout=layout),
        "document_type": hit.document_type,
        "source_file": hit.source_file,
        "page": hit.page,
        "title": hit.title,
        "excerpt": hit.excerpt,
    }


def case_hit_to_dict(case: DebugCaseRecord, *, layout) -> dict[str, Any]:
    """Convert one debug-case lookup hit to a JSON-serializable mapping."""
    return {
        "case_id": case.case_id,
        "project": case.project,
        "build": case.build,
        "scope": _scope_label(project=case.project, build=case.build, layout=layout),
        "title": case.title,
        "source_file": case.source_file,
        "document_type": case.document_type,
        "symptom": case.symptom,
        "suspected_nets": list(case.suspected_nets),
        "suspected_parts": list(case.suspected_parts),
        "steps": list(case.steps),
        "root_cause": case.root_cause,
        "case_citations": list(case.case_citations),
        "keywords": list(case.keywords),
        "chunk_ids": list(case.chunk_ids),
    }

def chunk_hit_to_dict(
    chunk: HybridChunk,
    *,
    layout,
    content_preview_chars: int = DEFAULT_CONTENT_PREVIEW_CHARS,
) -> dict[str, Any]:
    """Convert one retrieval chunk to a JSON-serializable mapping."""
    metadata = chunk.metadata
    project = str(metadata.get("project", ""))
    build = str(metadata.get("build", ""))
    content = chunk.content
    if content_preview_chars > 0 and len(content) > content_preview_chars:
        content = content[:content_preview_chars].rstrip() + "..."
    return {
        "chunk_id": chunk.chunk_id,
        "project": project,
        "build": build,
        "scope": _scope_label(project=project, build=build, layout=layout),
        "document_type": str(metadata.get("document_type", "")),
        "source_file": str(chunk.citation.get("source_file", "")),
        "page": int(chunk.citation.get("page") or metadata.get("page") or 0),
        "title": str(metadata.get("title", "")),
        "excerpt": str(chunk.citation.get("excerpt", "")),
        "content": content,
    }


def format_component_search(
    *,
    query: str,
    hits: list[ComponentHit],
    layout,
) -> str:
    """Format component lookup hits as JSON text for MCP clients."""
    payload = {
        "query": query,
        "hits": [component_hit_to_dict(hit, layout=layout) for hit in hits],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_case_search(
    *,
    query: str,
    hits: list[DebugCaseRecord],
    layout,
) -> str:
    """Format debug-case lookup hits as JSON text for MCP clients."""
    payload = {
        "query": query,
        "hits": [case_hit_to_dict(hit, layout=layout) for hit in hits],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def format_power_tree(result: dict[str, Any]) -> str:
    """Format a power-tree query result as JSON text for MCP clients."""
    return json.dumps(result, ensure_ascii=False, indent=2)


def format_rules(result: dict[str, Any]) -> str:
    """Format a rules list/evaluate payload as JSON text for MCP clients."""
    return json.dumps(result, ensure_ascii=False, indent=2)


def format_graph_query(result: dict[str, Any]) -> str:
    """Format a graph neighbors/path/nodes/node payload as JSON text."""
    return json.dumps(result, ensure_ascii=False, indent=2)


def format_retrieval_result(
    *,
    query: str,
    result: RetrievalResult,
    layout,
    document_type: str | None = None,
    content_preview_chars: int = DEFAULT_CONTENT_PREVIEW_CHARS,
) -> str:
    """Format ranked retrieval chunks as JSON text for MCP clients."""
    payload: dict[str, Any] = {
        "query": query,
        "document_type": document_type,
        "top_rerank_score": result.top_rerank_score,
        "hits": [
            chunk_hit_to_dict(
                chunk,
                layout=layout,
                content_preview_chars=content_preview_chars,
            )
            for chunk in result.chunks
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
