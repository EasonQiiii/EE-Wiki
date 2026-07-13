"""MCP server exposing EE-Wiki engineering retrieval tools."""

from __future__ import annotations

from ee_wiki.common.logging import get_logger
from ee_wiki.tools.context import ToolContext
from ee_wiki.tools.handlers import (
    engineering_search,
    list_projects,
    query_schematic,
    search_component,
    search_datasheet,
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
