"""Optional compact graph neighborhood text for RAG context (V3 P5).

Generation never opens the graph store. Callers load a :class:`GraphQuery`
(or let this helper open one from config) and attach the returned string to
:class:`~ee_wiki.retrieval.hybrid.engine.RetrievalResult.graph_enrichment`.
"""

from __future__ import annotations

from typing import Any

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.graph.query import GraphQuery, open_query
from ee_wiki.graph.store import GraphStoreError, JsonlGraphStore, graph_exists
from ee_wiki.retrieval.query_boost import query_boost_tokens

logger = get_logger(__name__)

GRAPH_ENRICHMENT_LIMITATIONS = (
    "Graph neighborhood is co-occurrence / heuristic connectivity from "
    "indexed metadata — not a CAD netlist. Prefer document citations for "
    "board-verified wiring."
)


def format_neighborhood_block(
    *,
    seeds: list[dict[str, Any]],
    neighbors: list[dict[str, Any]],
    max_lines: int = 24,
) -> str:
    """Render a compact multi-line graph neighborhood for LLM context.

    Args:
        seeds: Resolved seed node records (with ``id`` / ``type`` / ``scope``).
        neighbors: Neighbor records from :meth:`GraphQuery.neighbors`.
        max_lines: Cap on body lines after the header.

    Returns:
        Formatted block text, or empty string when nothing useful was found.
    """
    if not seeds and not neighbors:
        return ""
    lines: list[str] = [
        "[graph] kind=neighborhood "
        f"limitations={GRAPH_ENRICHMENT_LIMITATIONS}"
    ]
    for seed in seeds:
        lines.append(
            f"  seed id={seed.get('id')} type={seed.get('type')} "
            f"scope={seed.get('scope')} project={seed.get('project')} "
            f"build={seed.get('build')}"
        )
    for neighbor in neighbors:
        lines.append(
            f"  neighbor id={neighbor.get('id')} type={neighbor.get('type')} "
            f"scope={neighbor.get('scope')} hops={neighbor.get('hops', 1)} "
            f"project={neighbor.get('project')} build={neighbor.get('build')}"
        )
        if len(lines) >= max_lines + 1:
            lines.append("  …(truncated)")
            break
    return "\n".join(lines)


def build_graph_enrichment(
    query: str,
    *,
    graph_query: GraphQuery,
    project: str | None = None,
    build: str | None = None,
    max_hops: int = 1,
    max_nodes: int = 12,
    max_seeds: int = 3,
) -> str | None:
    """Resolve query tokens to graph nodes and format a compact neighborhood.

    Args:
        query: User or retrieval query text.
        graph_query: Loaded scope-aware graph query handle.
        project: Optional project filter.
        build: Optional build filter.
        max_hops: Neighbor traversal depth.
        max_nodes: Cap on total neighbor rows included.
        max_seeds: Cap on seed nodes resolved from query tokens.

    Returns:
        Formatted enrichment text, or ``None`` when no seeds resolve.
    """
    tokens = query_boost_tokens(query)
    if not tokens:
        return None

    seeds: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for token in tokens:
        if len(seeds) >= max_seeds:
            break
        resolved = graph_query.resolve_node(token, project=project, build=build)
        if not resolved or resolved in seen_ids:
            continue
        node = graph_query.get_node(resolved, project=project, build=build)
        if node is None:
            continue
        seen_ids.add(resolved)
        seeds.append(node)

    if not seeds:
        return None

    neighbors: list[dict[str, Any]] = []
    neighbor_ids: set[str] = set(seen_ids)
    for seed in seeds:
        seed_id = str(seed["id"])
        for neighbor in graph_query.neighbors(
            seed_id,
            project=project,
            build=build,
            max_hops=max_hops,
        ):
            nid = str(neighbor.get("id", ""))
            if not nid or nid in neighbor_ids:
                continue
            neighbor_ids.add(nid)
            neighbors.append(neighbor)
            if len(neighbors) >= max_nodes:
                break
        if len(neighbors) >= max_nodes:
            break

    text = format_neighborhood_block(seeds=seeds, neighbors=neighbors)
    return text or None


def try_graph_enrichment(
    query: str,
    *,
    config: AppConfig,
    project: str | None = None,
    build: str | None = None,
    graph_query: GraphQuery | None = None,
) -> str | None:
    """Optionally build graph enrichment when config enables it.

    Args:
        query: Retrieval query.
        config: Application configuration (reads ``retrieval.graph_enrichment*``).
        project: Optional project filter.
        build: Optional build filter.
        graph_query: Optional pre-loaded query handle; loaded from disk when omitted.

    Returns:
        Enrichment text, or ``None`` when disabled / unavailable / no matches.
    """
    retrieval = config.retrieval
    if not retrieval.graph_enrichment:
        return None

    gq = graph_query
    if gq is None:
        if not graph_exists(config.graph_dir):
            logger.debug("graph_enrichment skipped: no graph under %s", config.graph_dir)
            return None
        try:
            graph = JsonlGraphStore().load_graph(config.graph_dir)
        except GraphStoreError as exc:
            logger.warning("graph_enrichment skipped: failed to load graph: %s", exc)
            return None
        gq = open_query(
            graph,
            layout=config.data_layout,
            scope_inheritance=config.graph.scope_inheritance,
        )

    return build_graph_enrichment(
        query,
        graph_query=gq,
        project=project,
        build=build,
        max_hops=retrieval.graph_enrichment_max_hops,
        max_nodes=retrieval.graph_enrichment_max_nodes,
    )
