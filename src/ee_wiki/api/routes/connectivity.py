"""Schematic connectivity trace routes over ``*.connectivity.json`` (ADR 0009)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ee_wiki.api.deps import get_config, get_connectivity_query
from ee_wiki.api.models import ConnectivityTraceResponse
from ee_wiki.api.scope_params import resolve_request_scope
from ee_wiki.connectivity.query import ConnectivityQuery

router = APIRouter(prefix="/v1/schematic/connectivity", tags=["connectivity"])

_UNAVAILABLE = (
    "Connectivity sidecars unavailable. Re-ingest sch/ PDFs with "
    "schematic_pdf.connectivity.enabled and write_sidecar, then retry."
)


def _require_query(
    cq: ConnectivityQuery | None,
) -> ConnectivityQuery:
    if cq is None:
        raise HTTPException(status_code=503, detail=_UNAVAILABLE)
    return cq


def _to_response(result: dict) -> ConnectivityTraceResponse:
    return ConnectivityTraceResponse(
        query=str(result.get("query", "")),
        kind=str(result.get("kind", "")),
        found=bool(result.get("found", False)),
        authoritative=bool(result.get("authoritative", False)),
        authority=str(result.get("authority", "")),
        product=result.get("product"),
        project=result.get("project"),
        build=result.get("build"),
        resolved_net=result.get("resolved_net"),
        resolved_refdes=result.get("resolved_refdes"),
        match=result.get("match"),
        page=result.get("page"),
        pins=list(result.get("pins") or []),
        pin_count=int(result.get("pin_count") or len(result.get("pins") or [])),
        connectors=list(result.get("connectors") or []),
        modules=list(result.get("modules") or []),
        advisory_pins=list(result.get("advisory_pins") or []),
        advisory_connectors=list(result.get("advisory_connectors") or []),
        documents=list(result.get("documents") or []),
        limitations=str(result.get("limitations", "")),
        note=result.get("note"),
        error=result.get("error"),
    )


@router.get("/net", response_model=ConnectivityTraceResponse)
async def trace_net_route(
    q: str = Query(..., description="Net name (for example EDP_AUXP)"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    source_file: str | None = Query(
        default=None,
        description="Optional substring filter on schematic or sidecar path",
    ),
    cq: ConnectivityQuery | None = Depends(get_connectivity_query),
    config=Depends(get_config),
) -> ConnectivityTraceResponse:
    """Trace all pins on a net from ingested connectivity sidecars."""
    service = _require_query(cq)
    product, project, build = resolve_request_scope(config, product, project, build)
    result = service.resolve_trace(
        "net",
        q,
        product=product,
        project=project,
        build=build,
        source_file=source_file,
    )
    response = _to_response(result)
    if result.get("error") == "net query is empty":
        raise HTTPException(status_code=422, detail=result["error"])
    if result.get("authority") == "insufficient":
        raise HTTPException(
            status_code=409,
            detail=result.get("note") or f"No authoritative trace for net: {q}",
        )
    if not response.found:
        raise HTTPException(
            status_code=404,
            detail=f"Net not found in connectivity sidecars: {q}",
        )
    return response


@router.get("/pins", response_model=ConnectivityTraceResponse)
async def connector_pins_route(
    q: str = Query(..., description="Designator (for example J1 or U0500)"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    source_file: str | None = Query(default=None),
    cq: ConnectivityQuery | None = Depends(get_connectivity_query),
    config=Depends(get_config),
) -> ConnectivityTraceResponse:
    """List pin↔net bindings for a connector or part designator."""
    service = _require_query(cq)
    product, project, build = resolve_request_scope(config, product, project, build)
    result = service.resolve_trace(
        "pins",
        q,
        product=product,
        project=project,
        build=build,
        source_file=source_file,
    )
    response = _to_response(result)
    if result.get("error") == "refdes query is empty":
        raise HTTPException(status_code=422, detail=result["error"])
    if result.get("authority") == "insufficient":
        raise HTTPException(
            status_code=409,
            detail=result.get("note")
            or f"No authoritative pin trace for designator: {q}",
        )
    if not response.found:
        raise HTTPException(
            status_code=404,
            detail=f"Designator not found in connectivity sidecars: {q}",
        )
    return response


@router.get("/module-nets", response_model=ConnectivityTraceResponse)
async def module_nets_route(
    q: str = Query(..., description="Module zone label (for example OLED&CAMERA)"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    source_file: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    cq: ConnectivityQuery | None = Depends(get_connectivity_query),
    config=Depends(get_config),
) -> ConnectivityTraceResponse:
    """List nets associated with a schematic page module zone label."""
    service = _require_query(cq)
    product, project, build = resolve_request_scope(config, product, project, build)
    result = service.resolve_trace(
        "module",
        q,
        product=product,
        project=project,
        build=build,
        source_file=source_file,
        page=page,
    )
    response = _to_response(result)
    if result.get("error") == "module query is empty":
        raise HTTPException(status_code=422, detail=result["error"])
    if not response.found:
        raise HTTPException(
            status_code=404,
            detail=f"Module not found in connectivity sidecars: {q}",
        )
    return response
