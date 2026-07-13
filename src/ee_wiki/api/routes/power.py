"""Power-tree query route (V3 P3)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ee_wiki.api.deps import get_power_tree_query
from ee_wiki.api.models import PowerTreeResponse
from ee_wiki.graph.power_tree import PowerTreeQuery

router = APIRouter(prefix="/v1", tags=["power"])

PowerDirectionParam = Literal["feeds", "powers", "tree", "flags"]


@router.get("/power/tree", response_model=PowerTreeResponse)
async def query_power_tree(
    q: str = Query(
        default="",
        description="Rail, designator, part number, or node id (optional for direction=flags)",
    ),
    direction: PowerDirectionParam = Query(
        default="tree",
        description="feeds | powers | tree | flags",
    ),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    max_depth: int = Query(default=4, ge=1, le=12),
    power: PowerTreeQuery | None = Depends(get_power_tree_query),
) -> PowerTreeResponse:
    """Query the heuristic power tree (rails / supplies / derived_from)."""
    if power is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Knowledge graph not available. Run `python scripts/build_graph.py` "
                "after indexing, or disable graph.power_tree only if intentional."
            ),
        )
    if direction != "flags" and not q.strip():
        raise HTTPException(
            status_code=422,
            detail="Query parameter q is required unless direction=flags",
        )
    result = power.query(
        q,
        direction=direction,
        project=project,
        build=build,
        max_depth=max_depth,
    )
    return PowerTreeResponse(
        query=str(result.get("query", q)),
        direction=str(result.get("direction", direction)),
        project=project,
        build=build,
        resolved_id=result.get("resolved_id"),
        hits=list(result.get("hits") or []),
        feeds=list(result.get("feeds") or []),
        tree=result.get("tree"),
        flags=list(result.get("flags") or []),
        limitations=str(result.get("limitations", "")),
    )
