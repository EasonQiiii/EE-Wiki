"""Read-only engineering tool handlers backed by hybrid retrieval."""

from __future__ import annotations

import json

from ee_wiki.common.serialization import DATASHEET_DOCUMENT_TYPE, SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.graph.power_tree import PowerDirection, open_power_query
from ee_wiki.graph.query import GraphQuery, open_query
from ee_wiki.graph.store import GraphStoreError, JsonlGraphStore, graph_exists
from ee_wiki.knowledge.indexer.case_index import CaseIndexError, load_case_index
from ee_wiki.retrieval.index_inventory import inventory_to_dict
from ee_wiki.rules.engine import open_rule_engine
from ee_wiki.rules.errors import RulePackError
from ee_wiki.tools.context import ToolContext
from ee_wiki.tools.format import (
    format_case_search,
    format_component_search,
    format_graph_query,
    format_power_tree,
    format_retrieval_result,
    format_rules,
)


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


def search_debug_case(
    ctx: ToolContext,
    query: str,
    *,
    project: str | None = None,
    build: str | None = None,
    limit: int = 20,
) -> str:
    """Look up debug / failure-analysis cases by symptom, part, net, or case id.

    Args:
        ctx: Initialized tool context.
        query: Symptom text, part number, net name, or case id.
        project: Optional project filter.
        build: Optional build filter.
        limit: Maximum number of cases to return.

    Returns:
        JSON text with matching cases, citations, and scope labels.
    """
    hits = ctx.engine.search_cases(
        query,
        target_project=project,
        target_build=build,
        limit=limit,
    )
    return format_case_search(query=query, hits=hits, layout=ctx.config.data_layout)


def query_power_tree(
    ctx: ToolContext,
    query: str,
    *,
    direction: str = "tree",
    project: str | None = None,
    build: str | None = None,
    max_depth: int = 4,
) -> str:
    """Query the heuristic power tree (what feeds X / what Y powers / flags).

    Args:
        ctx: Initialized tool context.
        query: Rail name, designator, part number, or node id (empty for flags).
        direction: ``feeds``, ``powers``, ``tree``, or ``flags``.
        project: Optional project filter.
        build: Optional build filter.
        max_depth: Tree serialization depth for ``direction=tree``.

    Returns:
        JSON text with hits, tree text, and/or diagnostic flags.
    """
    config = ctx.config
    if not config.graph.power_tree:
        return format_power_tree(
            {
                "error": "graph.power_tree is disabled in config",
                "query": query,
                "direction": direction,
            }
        )
    if not graph_exists(config.graph_dir):
        return format_power_tree(
            {
                "error": (
                    f"Knowledge graph not found under {config.graph_dir}. "
                    "Run python scripts/build_graph.py after indexing."
                ),
                "query": query,
                "direction": direction,
            }
        )
    if direction not in {"feeds", "powers", "tree", "flags"}:
        return format_power_tree(
            {
                "error": f"Invalid direction {direction!r}; use feeds|powers|tree|flags",
                "query": query,
                "direction": direction,
            }
        )
    direction_typed: PowerDirection = direction  # type: ignore[assignment]
    try:
        graph = JsonlGraphStore().load_graph(config.graph_dir)
    except GraphStoreError as exc:
        return format_power_tree(
            {
                "error": f"Failed to load graph: {exc}",
                "query": query,
                "direction": direction,
            }
        )
    gq = open_query(
        graph,
        layout=config.data_layout,
        scope_inheritance=config.graph.scope_inheritance,
    )
    power = open_power_query(gq)
    result = power.query(
        query,
        direction=direction_typed,
        project=project,
        build=build,
        max_depth=max_depth,
    )
    return format_power_tree(result)


def _load_graph_query(ctx: ToolContext) -> tuple[GraphQuery | None, str | None]:
    """Load a GraphQuery for MCP tools, or return an error message."""
    config = ctx.config
    if not graph_exists(config.graph_dir):
        return None, (
            f"Knowledge graph not found under {config.graph_dir}. "
            "Run python scripts/build_graph.py after indexing."
        )
    try:
        graph = JsonlGraphStore().load_graph(config.graph_dir)
    except GraphStoreError as exc:
        return None, f"Failed to load graph: {exc}"
    return (
        open_query(
            graph,
            layout=config.data_layout,
            scope_inheritance=config.graph.scope_inheritance,
        ),
        None,
    )


def _parse_csv_list(raw: str | None) -> list[str] | None:
    if raw is None or not str(raw).strip():
        return None
    items = [part.strip() for part in str(raw).split(",") if part.strip()]
    return items or None


def graph_neighbors(
    ctx: ToolContext,
    query: str,
    *,
    project: str | None = None,
    build: str | None = None,
    max_hops: int = 1,
    edge_types: str | None = None,
) -> str:
    """Return neighboring graph nodes for a resolvable token or node id.

    Args:
        ctx: Initialized tool context.
        query: Node id, designator, net, rail, case, or part token.
        project: Optional project filter.
        build: Optional build filter.
        max_hops: Maximum traversal depth.
        edge_types: Optional comma-separated edge-type allowlist.

    Returns:
        JSON text with neighbors and resolved node id.
    """
    gq, error = _load_graph_query(ctx)
    if error or gq is None:
        return format_graph_query({"error": error or "Graph unavailable", "query": query})
    token = query.strip()
    edge_allow = _parse_csv_list(edge_types)
    resolved = gq.resolve_node(token, project=project, build=build)
    neighbors: list[dict] = []
    if resolved:
        neighbors = gq.neighbors(
            resolved,
            project=project,
            build=build,
            edge_types=edge_allow,
            max_hops=max_hops,
        )
    return format_graph_query(
        {
            "query": token,
            "resolved_id": resolved,
            "project": project,
            "build": build,
            "max_hops": max_hops,
            "edge_types": edge_allow,
            "neighbors": neighbors,
        }
    )


def graph_path(
    ctx: ToolContext,
    source: str,
    target: str,
    *,
    project: str | None = None,
    build: str | None = None,
    max_depth: int = 8,
    edge_types: str | None = None,
) -> str:
    """Return one shortest path between two resolvable graph nodes.

    Args:
        ctx: Initialized tool context.
        source: Start node id or token.
        target: End node id or token.
        project: Optional project filter.
        build: Optional build filter.
        max_depth: Maximum path length in edges.
        edge_types: Optional comma-separated edge-type allowlist.

    Returns:
        JSON text with path steps or found=false.
    """
    gq, error = _load_graph_query(ctx)
    if error or gq is None:
        return format_graph_query(
            {"error": error or "Graph unavailable", "source": source, "target": target}
        )
    edge_allow = _parse_csv_list(edge_types)
    resolved_source = gq.resolve_node(source.strip(), project=project, build=build)
    resolved_target = gq.resolve_node(target.strip(), project=project, build=build)
    path = None
    if resolved_source and resolved_target:
        path = gq.path(
            resolved_source,
            resolved_target,
            project=project,
            build=build,
            edge_types=edge_allow,
            max_depth=max_depth,
        )
    return format_graph_query(
        {
            "source": source.strip(),
            "target": target.strip(),
            "resolved_source": resolved_source,
            "resolved_target": resolved_target,
            "project": project,
            "build": build,
            "max_depth": max_depth,
            "edge_types": edge_allow,
            "path": path,
            "found": path is not None,
        }
    )


def graph_filter_by_scope(
    ctx: ToolContext,
    *,
    project: str | None = None,
    build: str | None = None,
    node_types: str | None = None,
    limit: int = 200,
) -> str:
    """List graph nodes matching project/build scope.

    Args:
        ctx: Initialized tool context.
        project: Optional project filter.
        build: Optional build filter.
        node_types: Optional comma-separated node-type allowlist.
        limit: Maximum nodes to return.

    Returns:
        JSON text with matching nodes.
    """
    gq, error = _load_graph_query(ctx)
    if error or gq is None:
        return format_graph_query({"error": error or "Graph unavailable"})
    type_allow = _parse_csv_list(node_types)
    nodes = gq.filter_by_scope(
        project=project,
        build=build,
        node_types=type_allow,
    )[: max(1, limit)]
    return format_graph_query(
        {
            "project": project,
            "build": build,
            "node_types": type_allow,
            "nodes": nodes,
            "count": len(nodes),
        }
    )


def open_graph_node(
    ctx: ToolContext,
    query: str,
    *,
    project: str | None = None,
    build: str | None = None,
) -> str:
    """Resolve and return a single graph node.

    Args:
        ctx: Initialized tool context.
        query: Node id or resolvable token.
        project: Optional project filter.
        build: Optional build filter.

    Returns:
        JSON text with the node payload when found.
    """
    gq, error = _load_graph_query(ctx)
    if error or gq is None:
        return format_graph_query({"error": error or "Graph unavailable", "query": query})
    token = query.strip()
    resolved = gq.resolve_node(token, project=project, build=build)
    node = gq.get_node(resolved, project=project, build=build) if resolved else None
    return format_graph_query(
        {
            "query": token,
            "resolved_id": resolved,
            "project": project,
            "build": build,
            "node": node,
        }
    )


def list_engineering_rules(
    ctx: ToolContext,
    *,
    include_disabled: bool = False,
) -> str:
    """List engineering rules from the configured YAML pack.

    Args:
        ctx: Initialized tool context.
        include_disabled: Include rules with ``enabled: false``.

    Returns:
        JSON text with rule definitions.
    """
    config = ctx.config
    if not config.rules.enabled:
        return format_rules({"error": "rules.enabled is false in config"})
    if not graph_exists(config.graph_dir):
        return format_rules(
            {
                "error": (
                    f"Knowledge graph not found under {config.graph_dir}. "
                    "Run python scripts/build_graph.py after indexing."
                )
            }
        )
    try:
        graph = JsonlGraphStore().load_graph(config.graph_dir)
    except GraphStoreError as exc:
        return format_rules({"error": f"Failed to load graph: {exc}"})

    gq = open_query(
        graph,
        layout=config.data_layout,
        scope_inheritance=config.graph.scope_inheritance,
    )
    power = open_power_query(gq) if config.graph.power_tree else None
    cases = None
    try:
        cases = load_case_index(config.indexes_dir)
    except CaseIndexError:
        cases = None
    try:
        engine = open_rule_engine(
            gq,
            config.rules_pack_dir,
            power_query=power,
            case_index=cases,
        )
    except RulePackError as exc:
        return format_rules({"error": f"Failed to load rule pack: {exc}"})
    rules = engine.list_rules(include_disabled=include_disabled)
    return format_rules(
        {
            "pack_dir": engine.pack.pack_dir,
            "rules": [r.to_dict() for r in rules],
        }
    )


def evaluate_engineering_rules(
    ctx: ToolContext,
    *,
    project: str | None = None,
    build: str | None = None,
    rule_ids: list[str] | None = None,
    include_disabled: bool = False,
) -> str:
    """Evaluate engineering rules against the knowledge graph and case index.

    Args:
        ctx: Initialized tool context.
        project: Optional project filter.
        build: Optional build filter.
        rule_ids: Optional subset of rule ids.
        include_disabled: Evaluate disabled rules when true.

    Returns:
        JSON text with pass/fail/insufficient results and citations.
    """
    config = ctx.config
    if not config.rules.enabled:
        return format_rules({"error": "rules.enabled is false in config"})
    if not graph_exists(config.graph_dir):
        return format_rules(
            {
                "error": (
                    f"Knowledge graph not found under {config.graph_dir}. "
                    "Run python scripts/build_graph.py after indexing."
                )
            }
        )
    try:
        graph = JsonlGraphStore().load_graph(config.graph_dir)
    except GraphStoreError as exc:
        return format_rules({"error": f"Failed to load graph: {exc}"})

    gq = open_query(
        graph,
        layout=config.data_layout,
        scope_inheritance=config.graph.scope_inheritance,
    )
    power = open_power_query(gq) if config.graph.power_tree else None
    cases = None
    try:
        cases = load_case_index(config.indexes_dir)
    except CaseIndexError:
        cases = None
    try:
        engine = open_rule_engine(
            gq,
            config.rules_pack_dir,
            power_query=power,
            case_index=cases,
        )
    except RulePackError as exc:
        return format_rules({"error": f"Failed to load rule pack: {exc}"})
    return format_rules(
        engine.evaluate_summary(
            rule_ids=rule_ids,
            project=project,
            build=build,
            include_disabled=include_disabled,
        )
    )


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


def list_projects(ctx: ToolContext) -> str:
    """Return indexed project/build inventory as JSON text.

    Args:
        ctx: Initialized tool context.

    Returns:
        JSON text with project paths, builds, and chunk counts.
    """
    inventory = ctx.engine.get_index_inventory()
    return json.dumps(inventory_to_dict(inventory), ensure_ascii=False, indent=2)
