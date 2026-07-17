"""Optional compact graph neighborhood text for RAG context (V3 P5).

Generation never opens the graph store. Callers load a :class:`GraphQuery`
(or let this helper open one from config) and attach the returned string to
:class:`~ee_wiki.retrieval.hybrid.engine.RetrievalResult.graph_enrichment`.
"""

from __future__ import annotations

import re
from typing import Any

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.graph.power import is_rail_like_net
from ee_wiki.graph.power_tree import open_power_query
from ee_wiki.graph.query import GraphQuery, open_query
from ee_wiki.graph.store import GraphStoreError, JsonlGraphStore, graph_exists
from ee_wiki.retrieval.query_boost import query_boost_tokens

logger = get_logger(__name__)

GRAPH_ENRICHMENT_LIMITATIONS = (
    "Graph neighborhood is co-occurrence / heuristic connectivity from "
    "indexed metadata — not a CAD netlist. Prefer document citations for "
    "board-verified wiring."
)

# Chinese keywords are substring-safe; English terms use word boundaries so
# generic phrases like "missing capacitor" or "current build" do not route here.
_CHINESE_POWER_KEYWORDS = ("供电", "电源", "丢失", "掉电", "上电", "电压", "电流")
_ENGLISH_POWER_KEYWORDS_RE = re.compile(
    r"\b("
    r"rail|rails|supply|supplies|supplied|supplier|"
    r"voltage|regulator|ldo|pmic|buck|boost|feeds|vbias|powers"
    r")\b",
    re.IGNORECASE,
)


def is_power_query(query: str) -> bool:
    """Heuristic gate: does the query ask about power rails / supply chains?

    Args:
        query: User or retrieval query text.

    Returns:
        ``True`` when a power keyword or rail-like token is present.
    """
    if any(kw in query for kw in _CHINESE_POWER_KEYWORDS):
        return True
    if _ENGLISH_POWER_KEYWORDS_RE.search(query):
        return True
    for token in query_boost_tokens(query):
        if is_rail_like_net(token) or is_rail_like_net(token.removeprefix("NET_")):
            return True
    return False


def _resolve_power_seed(
    power_query: Any,
    tokens: list[str],
    *,
    project: str | None,
    build: str | None,
) -> str | None:
    """Resolve the first power-relevant token, folding separators (``V_BAT``→``VBAT``).

    Args:
        power_query: A :class:`PowerTreeQuery` bound to the loaded graph.
        tokens: Candidate tokens from the query.
        project: Optional project scope.
        build: Optional build scope.

    Returns:
        Resolved node id, or ``None`` when no token maps to a graph node.
    """
    for token in tokens:
        cleaned = token.strip()
        if not cleaned:
            continue
        for candidate in (cleaned, cleaned.replace("_", ""), cleaned.replace("-", "")):
            if not candidate:
                continue
            resolved = power_query.resolve(candidate, project=project, build=build)
            if resolved:
                return resolved
    return None


def format_power_tree_block(
    *,
    seed_id: str,
    feeds: list[dict[str, Any]],
    powers: list[dict[str, Any]],
    flags: list[Any],
    confidence: str,
) -> str:
    """Render a directed power-tree enrichment block for LLM context.

    Args:
        seed_id: Resolved seed node id.
        feeds: Upstream sources (``what_feeds`` results).
        powers: Downstream loads (``what_powers`` results).
        flags: Scope-relevant :class:`PowerFlag` diagnostics.
        confidence: ``high`` when any directed edge/flag was found, else ``low``.

    Returns:
        Formatted multi-line block, or empty string when nothing to show.
    """
    lines: list[str] = [
        f"[graph] kind=power_tree confidence={confidence} "
        f"limitations={GRAPH_ENRICHMENT_LIMITATIONS}",
        f"  seed id={seed_id}",
    ]
    if feeds:
        lines.append("  feeds (upstream sources):")
        for item in feeds:
            via = _edge_kind(item) or item.get("relation") or "supplies"
            lines.append(f"    - {item.get('type')}:{item.get('id')} via {via}")
    if powers:
        lines.append("  powers (downstream loads):")
        for item in powers:
            via = _edge_kind(item) or "supplies"
            lines.append(f"    - {item.get('type')}:{item.get('id')} via {via}")
    if flags:
        lines.append("  flags:")
        for flag in flags:
            lines.append(f"    - {flag.code}: {flag.message}")
    if not (feeds or powers or flags):
        lines.append("  (no directed power edges resolved for this seed)")
    return "\n".join(lines)


def _edge_kind(item: dict[str, Any]) -> str | None:
    """Best-effort edge label: prefer ``kind`` attribute, fall back to type."""
    via_edge = item.get("via_edge") or {}
    if not isinstance(via_edge, dict):
        return None
    kind = (via_edge.get("attributes") or {}).get("kind")
    if kind:
        return str(kind)
    return via_edge.get("type")


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
    power_tree: bool = True,
) -> str | None:
    """Resolve query tokens to graph nodes and format a compact neighborhood.

    Args:
        query: User or retrieval query text.
        graph_query: Loaded scope-aware graph query handle.
        project: Optional project filter.
        build: Optional build filter.
        max_hops: Neighbor traversal depth (generic neighborhood path).
        max_nodes: Cap on total neighbor rows included (generic path).
        max_seeds: Cap on seed nodes resolved from query tokens.
        power_tree: When a power/rail intent is detected, route through the
            directed :class:`PowerTreeQuery` instead of the undirected
            neighborhood. Set ``False`` to force the generic path.

    Returns:
        Formatted enrichment text, or ``None`` when no seeds resolve.
    """
    tokens = query_boost_tokens(query)
    if not tokens:
        return None

    # Power-intent routing: reuse the already-correct directed power tree
    # (what_feeds / what_powers / flags) for rail/regulator questions instead
    # of the undirected, all-edge-mixed generic neighborhood. This keeps the
    # supply chain readable (upstream vs downstream) and feeds the V4 Power
    # Engineer agent a trustworthy structured view.
    if power_tree and is_power_query(query):
        pw = open_power_query(graph_query)
        seed_id = _resolve_power_seed(pw, tokens, project=project, build=build)
        if seed_id is not None:
            feeds = pw.what_feeds(seed_id, project=project, build=build)
            powers = pw.what_powers(seed_id, project=project, build=build)
            related_ids = (
                {seed_id}
                | {str(f.get("id", "")) for f in feeds}
                | {str(p.get("id", "")) for p in powers}
            )
            scoped_flags = [
                flag
                for flag in pw.flags(project=project, build=build)
                if any(nid in related_ids for nid in flag.node_ids)
            ]
            if feeds or powers or scoped_flags:
                text = format_power_tree_block(
                    seed_id=seed_id,
                    feeds=feeds,
                    powers=powers,
                    flags=scoped_flags,
                    confidence="high",
                )
                return text or None
            # Resolved seed but no directed edges/flags — fall through to the
            # generic neighborhood instead of emitting a low-confidence stub.
        # No power seed resolved — fall through to the generic neighborhood so
        # the query still gets graph context when a non-power node matches.

    # --- generic undirected neighborhood (unchanged) ---
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
        power_tree=retrieval.graph_enrichment_power_tree,
    )
