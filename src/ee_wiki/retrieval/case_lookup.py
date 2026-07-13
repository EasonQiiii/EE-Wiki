"""Debug-case index lookups for retrieval boosting and HTTP/MCP search."""

from __future__ import annotations

import re

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope
from ee_wiki.knowledge.indexer.case_index import CaseIndex, DebugCaseRecord

CASE_LOOKUP_BOOST = 3
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_/.:]{1,}")


def _allowed_scopes(
    *,
    layout: DataLayoutConfig,
    target_project: str | None,
    target_build: str | None,
    scope_inheritance: bool,
) -> set[tuple[str, str]] | None:
    """Return allowed ``(project, build)`` pairs, or ``None`` for no scope filter."""
    if not target_project and not target_build:
        return None
    project = target_project or layout.enterprise_project
    build = target_build or layout.project_shared_build
    if not scope_inheritance:
        return {(project, build)}
    return set(expand_retrieval_scope(project, build, layout))


def _case_in_scope(
    case: DebugCaseRecord,
    allowed_scopes: set[tuple[str, str]] | None,
) -> bool:
    if allowed_scopes is None:
        return True
    return (case.project, case.build) in allowed_scopes


def _query_tokens(query: str) -> list[str]:
    return [m.group(0).upper() for m in _TOKEN_RE.finditer(query)]


def _score_case(case: DebugCaseRecord, tokens: list[str]) -> int:
    if not tokens:
        return 0
    haystack = case.searchable_text()
    score = 0
    for token in tokens:
        if token in haystack:
            score += 1
            if token == case.case_id.upper():
                score += 2
            if token in {p.upper() for p in case.suspected_parts}:
                score += 1
            if token in {n.upper() for n in case.suspected_nets}:
                score += 1
    return score


def lookup_case_chunk_ids(
    case_index: CaseIndex | None,
    tokens: list[str],
    *,
    layout: DataLayoutConfig,
    target_project: str | None = None,
    target_build: str | None = None,
    scope_inheritance: bool = True,
) -> set[str]:
    """Return chunk IDs belonging to cases that match any query token.

    Args:
        case_index: Loaded debug-case index.
        tokens: Query tokens (already uppercased preferred).
        layout: Path naming configuration for scope expansion.
        target_project: Optional project filter.
        target_build: Optional build filter.
        scope_inheritance: Whether to expand scope upward when filtering.

    Returns:
        Matching ``chunk_id`` values from matching cases.
    """
    if case_index is None or not tokens:
        return set()

    allowed_scopes = _allowed_scopes(
        layout=layout,
        target_project=target_project,
        target_build=target_build,
        scope_inheritance=scope_inheritance,
    )
    normalized = [token.strip().upper() for token in tokens if token.strip()]
    matched: set[str] = set()
    for case in case_index.cases:
        if not _case_in_scope(case, allowed_scopes):
            continue
        if _score_case(case, normalized) <= 0:
            continue
        matched.update(case.chunk_ids)
    return matched


def search_cases(
    case_index: CaseIndex | None,
    query: str,
    *,
    layout: DataLayoutConfig,
    target_project: str | None = None,
    target_build: str | None = None,
    scope_inheritance: bool = True,
    limit: int = 20,
) -> list[DebugCaseRecord]:
    """Search the debug-case index by symptom, part, net, or case id.

    Args:
        case_index: Loaded debug-case index.
        query: Natural language or keyword query.
        layout: Path naming configuration for scope expansion.
        target_project: Optional project filter.
        target_build: Optional build filter.
        scope_inheritance: Whether to expand scope upward when filtering.
        limit: Maximum number of cases to return.

    Returns:
        Matching cases ranked by token overlap (highest first).
    """
    if case_index is None:
        return []

    tokens = _query_tokens(query)
    if not tokens:
        return []

    allowed_scopes = _allowed_scopes(
        layout=layout,
        target_project=target_project,
        target_build=target_build,
        scope_inheritance=scope_inheritance,
    )
    scored: list[tuple[int, DebugCaseRecord]] = []
    for case in case_index.cases:
        if not _case_in_scope(case, allowed_scopes):
            continue
        score = _score_case(case, tokens)
        if score > 0:
            scored.append((score, case))

    scored.sort(key=lambda item: (-item[0], item[1].project, item[1].build, item[1].case_id))
    return [case for _score, case in scored[:limit]]
