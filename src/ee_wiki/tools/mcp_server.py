"""MCP server exposing EE-Wiki engineering retrieval tools via ToolBus."""

from __future__ import annotations

from ee_wiki.common.logging import get_logger
from ee_wiki.tools.bus import ToolBus, open_tool_bus
from ee_wiki.tools.context import ToolContext
from ee_wiki.tools.scope import ScopeEnvelope

logger = get_logger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised via optional extra
    raise ImportError(
        "MCP support requires the optional 'tools' extra: pip install -e '.[tools]'"
    ) from exc

mcp = FastMCP("ee-wiki")
_tool_context: ToolContext | None = None
_tool_bus: ToolBus | None = None


def _get_context() -> ToolContext:
    """Return a lazily initialized tool context for MCP tool calls."""
    global _tool_context
    if _tool_context is None:
        logger.info("Initializing EE-Wiki MCP tool context")
        _tool_context = ToolContext.from_config()
    return _tool_context


def _get_bus() -> ToolBus:
    """Return a lazily initialized ToolBus shared by all MCP tools."""
    global _tool_bus
    if _tool_bus is None:
        ctx = _get_context()
        cfg = ctx.config.agents
        _tool_bus = open_tool_bus(
            ctx,
            timeout_seconds=cfg.tool_timeout_seconds,
            max_concurrent=cfg.max_concurrent_tools,
            span_log=ctx.config.agents_span_log,
        )
    return _tool_bus


def _call(
    name: str,
    args: dict,
    *,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
) -> str:
    """Invoke a tool through ToolBus with an MCP caller id."""
    scope = ScopeEnvelope(product=product, project=project, build=build)
    result = _get_bus().call(
        name,
        args,
        caller_id="mcp",
        scope=scope,
    )
    if not result.ok:
        return f'{{"error": {result.error!r}, "tool": {name!r}, "ok": false}}'
    return result.text


@mcp.tool()
def search_component_tool(
    query: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    limit: int = 20,
) -> str:
    """Look up a schematic designator or IC part number in the component index."""
    return _call(
        "search_component",
        {"query": query, "limit": limit},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def search_debug_case_tool(
    query: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    limit: int = 20,
) -> str:
    """Search debug / failure-analysis cases by symptom, part, net, or case id."""
    return _call(
        "search_debug_case",
        {"query": query, "limit": limit},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def query_power_tree_tool(
    query: str = "",
    direction: str = "tree",
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    max_depth: int = 4,
) -> str:
    """Query heuristic power tree: what feeds X, what Y powers, tree text, or flags."""
    return _call(
        "query_power_tree",
        {"query": query, "direction": direction, "max_depth": max_depth},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def list_rules_tool(include_disabled: bool = False) -> str:
    """List engineering rules from the configured YAML pack (V3 P4)."""
    return _call(
        "list_engineering_rules",
        {"include_disabled": include_disabled},
    )


@mcp.tool()
def evaluate_rules_tool(
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    rule_id: str | None = None,
    include_disabled: bool = False,
) -> str:
    """Evaluate engineering rules (pass/fail/insufficient) against graph + cases."""
    return _call(
        "evaluate_engineering_rules",
        {"rule_id": rule_id, "include_disabled": include_disabled},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def graph_neighbors_tool(
    query: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    max_hops: int = 1,
    edge_types: str | None = None,
) -> str:
    """Return neighboring knowledge-graph nodes for a designator, net, rail, or node id."""
    return _call(
        "graph_neighbors",
        {"query": query, "max_hops": max_hops, "edge_types": edge_types},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def graph_path_tool(
    source: str,
    target: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    max_depth: int = 8,
    edge_types: str | None = None,
) -> str:
    """Return one shortest path between two knowledge-graph nodes when found."""
    return _call(
        "graph_path",
        {
            "source": source,
            "target": target,
            "max_depth": max_depth,
            "edge_types": edge_types,
        },
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def graph_filter_tool(
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    node_types: str | None = None,
    limit: int = 200,
) -> str:
    """List knowledge-graph nodes matching project/build scope (with inheritance)."""
    return _call(
        "graph_filter_by_scope",
        {"node_types": node_types, "limit": limit},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def open_graph_node_tool(
    query: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
) -> str:
    """Resolve and open one knowledge-graph node (designator, net, rail, case, or id)."""
    return _call(
        "open_graph_node",
        {"query": query},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def query_schematic_tool(
    query: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve schematic knowledge chunks for wiring, interfaces, or page-level facts."""
    return _call(
        "query_schematic",
        {"query": query, "top_k": top_k},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def search_datasheet_tool(
    query: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve datasheet knowledge chunks for part specs, pinouts, or limits."""
    return _call(
        "search_datasheet",
        {"query": query, "top_k": top_k},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def list_projects_tool() -> str:
    """List indexed project/build paths and chunk counts in the knowledge base."""
    return _call("list_projects", {})


@mcp.tool()
def engineering_search_tool(
    query: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    document_type: str | None = None,
    top_k: int | None = None,
) -> str:
    """Retrieve ranked engineering knowledge across notes, SOPs, schematics, and datasheets."""
    return _call(
        "engineering_search",
        {"query": query, "document_type": document_type, "top_k": top_k},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def trace_net_tool(
    net: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    source_file: str | None = None,
) -> str:
    """Trace all pins on a net from schematic connectivity sidecars (netlist/boardview)."""
    return _call(
        "trace_net",
        {"net": net, "source_file": source_file},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def connector_pins_tool(
    refdes: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    source_file: str | None = None,
) -> str:
    """List pin↔net bindings for a connector or part from connectivity sidecars."""
    return _call(
        "connector_pins",
        {"refdes": refdes, "source_file": source_file},
        product=product,
        project=project,
        build=build,
    )


@mcp.tool()
def module_nets_tool(
    module: str,
    product: str | None = None,
    project: str | None = None,
    build: str | None = None,
    source_file: str | None = None,
    page: int | None = None,
) -> str:
    """List nets for a schematic page module zone from connectivity sidecars."""
    return _call(
        "module_nets",
        {"module": module, "source_file": source_file, "page": page},
        product=product,
        project=project,
        build=build,
    )


def run_stdio() -> None:
    """Start the MCP server on stdio transport."""
    mcp.run()
