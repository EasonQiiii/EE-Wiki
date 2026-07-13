"""MCP server exposing EE-Wiki engineering retrieval tools."""

from __future__ import annotations

from ee_wiki.common.logging import get_logger
from ee_wiki.tools.context import ToolContext
from ee_wiki.tools.handlers import (
    engineering_search,
    evaluate_engineering_rules,
    graph_filter_by_scope,
    graph_neighbors,
    graph_path,
    list_engineering_rules,
    list_projects,
    open_graph_node,
    query_power_tree,
    query_schematic,
    search_component,
    search_datasheet,
    search_debug_case,
)

logger = get_logger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised via optional extra
    raise ImportError(
        "MCP support requires the optional 'tools' extra: pip install -e '.[tools]'"
    ) from exc

mcp = FastMCP("ee-wiki")
_tool_context: ToolContext | None = None


def _get_context() -> ToolContext:
    """Return a lazily initialized tool context for MCP tool calls."""
    global _tool_context
    if _tool_context is None:
        logger.info("Initializing EE-Wiki MCP tool context")
        _tool_context = ToolContext.from_config()
    return _tool_context


@mcp.tool()
def search_component_tool(
    query: str,
    project: str | None = None,
    build: str | None = None,
    limit: int = 20,
) -> str:
    """Look up a schematic designator or IC part number in the component index."""
    return search_component(
        _get_context(),
        query,
        project=project,
        build=build,
        limit=limit,
    )


@mcp.tool()
def search_debug_case_tool(
    query: str,
    project: str | None = None,
    build: str | None = None,
    limit: int = 20,
) -> str:
    """Search debug / failure-analysis cases by symptom, part, net, or case id."""
    return search_debug_case(
        _get_context(),
        query,
        project=project,
        build=build,
        limit=limit,
    )


@mcp.tool()
def query_power_tree_tool(
    query: str = "",
    direction: str = "tree",
    project: str | None = None,
    build: str | None = None,
    max_depth: int = 4,
) -> str:
    """Query heuristic power tree: what feeds X, what Y powers, tree text, or flags."""
    return query_power_tree(
        _get_context(),
        query,
        direction=direction,
        project=project,
        build=build,
        max_depth=max_depth,
    )


@mcp.tool()
def list_rules_tool(include_disabled: bool = False) -> str:
    """List engineering rules from the configured YAML pack (V3 P4)."""
    return list_engineering_rules(
        _get_context(),
        include_disabled=include_disabled,
    )


@mcp.tool()
def evaluate_rules_tool(
    project: str | None = None,
    build: str | None = None,
    rule_id: str | None = None,
    include_disabled: bool = False,
) -> str:
    """Evaluate engineering rules (pass/fail/insufficient) against graph + cases."""
    rule_ids = [rule_id] if rule_id else None
    return evaluate_engineering_rules(
        _get_context(),
        project=project,
        build=build,
        rule_ids=rule_ids,
        include_disabled=include_disabled,
    )


@mcp.tool()
def graph_neighbors_tool(
    query: str,
    project: str | None = None,
    build: str | None = None,
    max_hops: int = 1,
    edge_types: str | None = None,
) -> str:
    """Return neighboring knowledge-graph nodes for a designator, net, rail, or node id."""
    return graph_neighbors(
        _get_context(),
        query,
        project=project,
        build=build,
        max_hops=max_hops,
        edge_types=edge_types,
    )


@mcp.tool()
def graph_path_tool(
    source: str,
    target: str,
    project: str | None = None,
    build: str | None = None,
    max_depth: int = 8,
    edge_types: str | None = None,
) -> str:
    """Return one shortest path between two knowledge-graph nodes when found."""
    return graph_path(
        _get_context(),
        source,
        target,
        project=project,
        build=build,
        max_depth=max_depth,
        edge_types=edge_types,
    )


@mcp.tool()
def graph_filter_tool(
    project: str | None = None,
    build: str | None = None,
    node_types: str | None = None,
    limit: int = 200,
) -> str:
    """List knowledge-graph nodes matching project/build scope (with inheritance)."""
    return graph_filter_by_scope(
        _get_context(),
        project=project,
        build=build,
        node_types=node_types,
        limit=limit,
    )


@mcp.tool()
def open_graph_node_tool(
    query: str,
    project: str | None = None,
    build: str | None = None,
) -> str:
    """Resolve and open one knowledge-graph node (designator, net, rail, case, or id)."""
    return open_graph_node(
        _get_context(),
        query,
        project=project,
        build=build,
    )


@mcp.tool()
def query_schematic_tool(
    query: str,
    project: str | None = None,
    build: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve schematic knowledge chunks for wiring, interfaces, or page-level facts."""
    return query_schematic(
        _get_context(),
        query,
        project=project,
        build=build,
        top_k=top_k,
    )


@mcp.tool()
def search_datasheet_tool(
    query: str,
    project: str | None = None,
    build: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve datasheet knowledge chunks for part specs, pinouts, or limits."""
    return search_datasheet(
        _get_context(),
        query,
        project=project,
        build=build,
        top_k=top_k,
    )


@mcp.tool()
def list_projects_tool() -> str:
    """List indexed project/build paths and chunk counts in the knowledge base."""
    return list_projects(_get_context())


@mcp.tool()
def engineering_search_tool(
    query: str,
    project: str | None = None,
    build: str | None = None,
    document_type: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve ranked engineering knowledge across notes, SOPs, schematics, and datasheets."""
    return engineering_search(
        _get_context(),
        query,
        project=project,
        build=build,
        document_type=document_type,
        top_k=top_k,
    )


def run_stdio() -> None:
    """Start the MCP server on stdio transport."""
    mcp.run()
