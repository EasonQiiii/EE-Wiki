"""Knowledge-graph query routes (V3 P5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ee_wiki.api.deps import get_config, get_graph_query
from ee_wiki.api.models import (
    GraphNeighborsResponse,
    GraphNodeResponse,
    GraphNodesResponse,
    GraphPathResponse,
)
from ee_wiki.api.scope_params import resolve_request_scope
from ee_wiki.graph.query import GraphQuery

router = APIRouter(prefix="/v1/graph", tags=["graph"])

_GRAPH_UNAVAILABLE = (
    "Knowledge graph not available. Run `python scripts/build_graph.py` after indexing."
)


def _parse_csv_list(raw: str | None) -> list[str] | None:
    """Split a comma-separated query param into a non-empty list, or ``None``."""
    if raw is None:
        return None
    items = [part.strip() for part in raw.split(",") if part.strip()]
    return items or None


@router.get("/node", response_model=GraphNodeResponse)
async def open_graph_node(
    q: str = Query(..., description="Node id, designator, net, rail, case, or part"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    gq: GraphQuery | None = Depends(get_graph_query),
    config=Depends(get_config),
) -> GraphNodeResponse:
    """Resolve and return one graph node (thin open-node helper)."""
    if gq is None:
        raise HTTPException(status_code=503, detail=_GRAPH_UNAVAILABLE)
    product, project, build = resolve_request_scope(config, product, project, build)
    token = q.strip()
    if not token:
        raise HTTPException(status_code=422, detail="Query parameter q is required")
    resolved = gq.resolve_node(token, product=product, project=project, build=build)
    node = (
        gq.get_node(resolved, product=product, project=project, build=build)
        if resolved
        else None
    )
    return GraphNodeResponse(
        query=token,
        resolved_id=resolved,
        product=product,
        project=project,
        build=build,
        node=node,
    )


@router.get("/neighbors", response_model=GraphNeighborsResponse)
async def graph_neighbors(
    q: str = Query(..., description="Node id or resolvable token (designator/net/rail/…)"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    max_hops: int = Query(default=1, ge=1, le=6),
    edge_types: str | None = Query(
        default=None,
        description="Optional comma-separated edge-type allowlist",
    ),
    gq: GraphQuery | None = Depends(get_graph_query),
    config=Depends(get_config),
) -> GraphNeighborsResponse:
    """Return neighboring nodes within ``max_hops`` of the resolved node."""
    if gq is None:
        raise HTTPException(status_code=503, detail=_GRAPH_UNAVAILABLE)
    product, project, build = resolve_request_scope(config, product, project, build)
    token = q.strip()
    if not token:
        raise HTTPException(status_code=422, detail="Query parameter q is required")
    resolved = gq.resolve_node(token, product=product, project=project, build=build)
    edge_allow = _parse_csv_list(edge_types)
    neighbors: list[dict] = []
    if resolved:
        neighbors = gq.neighbors(
            resolved,
            product=product,
            project=project,
            build=build,
            edge_types=edge_allow,
            max_hops=max_hops,
        )
    return GraphNeighborsResponse(
        node_id=token,
        resolved_id=resolved,
        product=product,
        project=project,
        build=build,
        max_hops=max_hops,
        edge_types=edge_allow,
        neighbors=neighbors,
    )


@router.get("/path", response_model=GraphPathResponse)
async def graph_path(
    source: str = Query(..., description="Start node id or resolvable token"),
    target: str = Query(..., description="End node id or resolvable token"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    max_depth: int = Query(default=8, ge=1, le=16),
    edge_types: str | None = Query(
        default=None,
        description="Optional comma-separated edge-type allowlist",
    ),
    gq: GraphQuery | None = Depends(get_graph_query),
    config=Depends(get_config),
) -> GraphPathResponse:
    """Return one shortest path between two resolved nodes, if found."""
    if gq is None:
        raise HTTPException(status_code=503, detail=_GRAPH_UNAVAILABLE)
    product, project, build = resolve_request_scope(config, product, project, build)
    src_token = source.strip()
    tgt_token = target.strip()
    if not src_token or not tgt_token:
        raise HTTPException(
            status_code=422,
            detail="Query parameters source and target are required",
        )
    resolved_source = gq.resolve_node(src_token, product=product, project=project, build=build)
    resolved_target = gq.resolve_node(tgt_token, product=product, project=project, build=build)
    edge_allow = _parse_csv_list(edge_types)
    path: list[dict] | None = None
    if resolved_source and resolved_target:
        path = gq.path(
            resolved_source,
            resolved_target,
            product=product,
            project=project,
            build=build,
            edge_types=edge_allow,
            max_depth=max_depth,
        )
    return GraphPathResponse(
        source=src_token,
        target=tgt_token,
        resolved_source=resolved_source,
        resolved_target=resolved_target,
        product=product,
        project=project,
        build=build,
        max_depth=max_depth,
        edge_types=edge_allow,
        path=path,
        found=path is not None,
    )


@router.get("/nodes", response_model=GraphNodesResponse)
async def graph_filter_by_scope(
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    node_types: str | None = Query(
        default=None,
        description="Optional comma-separated node-type allowlist",
    ),
    limit: int = Query(default=200, ge=1, le=2000),
    gq: GraphQuery | None = Depends(get_graph_query),
    config=Depends(get_config),
) -> GraphNodesResponse:
    """List nodes matching project/build scope (with inheritance)."""
    if gq is None:
        raise HTTPException(status_code=503, detail=_GRAPH_UNAVAILABLE)
    product, project, build = resolve_request_scope(config, product, project, build)
    type_allow = _parse_csv_list(node_types)
    nodes = gq.filter_by_scope(
        product=product,
        project=project,
        build=build,
        node_types=type_allow,
    )
    truncated = nodes[:limit]
    return GraphNodesResponse(
        product=product,
        project=project,
        build=build,
        node_types=type_allow,
        nodes=truncated,
        count=len(truncated),
    )
