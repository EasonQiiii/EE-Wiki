"""Component-index lookups for retrieval boosting and HTTP search."""

from __future__ import annotations

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.path_metadata import allowed_scope_triples
from ee_wiki.knowledge.indexer.component_index import ComponentHit, ComponentIndex

COMPONENT_LOOKUP_BOOST = 3


def _hit_in_scope(
    hit: ComponentHit,
    allowed_scopes: set[tuple[str, str, str]] | None,
) -> bool:
    if allowed_scopes is None:
        return True
    return (hit.product, hit.project, hit.build) in allowed_scopes


def lookup_tokens(
    component_index: ComponentIndex | None,
    tokens: list[str],
    *,
    layout: DataLayoutConfig,
    target_product: str | None = None,
    target_project: str | None = None,
    target_build: str | None = None,
    scope_inheritance: bool = True,
) -> set[str]:
    """Return chunk IDs whose component keys match any query token.

    Args:
        component_index: Loaded component lookup index.
        tokens: Query tokens from :func:`query_boost_tokens`.
        layout: Path naming configuration for scope expansion.
        target_product: Optional product filter.
        target_project: Optional project filter.
        target_build: Optional build filter.
        scope_inheritance: Whether to expand scope upward when filtering.

    Returns:
        Matching ``chunk_id`` values.
    """
    if component_index is None or not tokens:
        return set()

    allowed_scopes = allowed_scope_triples(
        layout,
        product=target_product,
        project=target_project,
        build=target_build,
        scope_inheritance=scope_inheritance,
    )
    matched: set[str] = set()
    for token in tokens:
        key = token.strip().upper()
        if not key:
            continue
        for hit in component_index.entries.get(key, []):
            if _hit_in_scope(hit, allowed_scopes):
                matched.add(hit.chunk_id)
    return matched


def search_components(
    component_index: ComponentIndex | None,
    query: str,
    *,
    layout: DataLayoutConfig,
    target_product: str | None = None,
    target_project: str | None = None,
    target_build: str | None = None,
    scope_inheritance: bool = True,
    limit: int = 20,
) -> list[ComponentHit]:
    """Search the component index for one key and return scoped hits.

    Args:
        component_index: Loaded component lookup index.
        query: Part number or designator to look up.
        layout: Path naming configuration for scope expansion.
        target_product: Optional product filter.
        target_project: Optional project filter.
        target_build: Optional build filter.
        scope_inheritance: Whether to expand scope upward when filtering.
        limit: Maximum number of hits to return.

    Returns:
        Matching component hits, deduplicated by ``chunk_id``.
    """
    if component_index is None:
        return []

    key = query.strip().upper()
    if not key:
        return []

    allowed_scopes = allowed_scope_triples(
        layout,
        product=target_product,
        project=target_project,
        build=target_build,
        scope_inheritance=scope_inheritance,
    )
    hits: list[ComponentHit] = []
    seen_chunk_ids: set[str] = set()
    for hit in component_index.entries.get(key, []):
        if not _hit_in_scope(hit, allowed_scopes):
            continue
        if hit.chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(hit.chunk_id)
        hits.append(hit)
        if len(hits) >= limit:
            break
    return hits
