"""Engineering rules HTTP routes (V3 P4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ee_wiki.api.deps import get_config, get_rule_engine
from ee_wiki.api.models import (
    RuleDefinitionModel,
    RuleEvaluateResponse,
    RuleListResponse,
    RuleResultModel,
)
from ee_wiki.api.scope_params import resolve_request_scope
from ee_wiki.rules.engine import RuleEngine

router = APIRouter(prefix="/v1", tags=["rules"])


@router.get("/rules", response_model=RuleListResponse)
async def list_rules(
    include_disabled: bool = Query(default=False),
    engine: RuleEngine | None = Depends(get_rule_engine),
) -> RuleListResponse:
    """List engineering rules from the configured YAML pack."""
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Rules engine unavailable. Ensure rules.enabled is true, "
                "config/rules/ exists, and the knowledge graph is built "
                "(python scripts/build_graph.py)."
            ),
        )
    rules = engine.list_rules(include_disabled=include_disabled)
    return RuleListResponse(
        pack_dir=engine.pack.pack_dir,
        rules=[RuleDefinitionModel(**r.to_dict()) for r in rules],
    )


@router.get("/rules/evaluate", response_model=RuleEvaluateResponse)
async def evaluate_rules(
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    rule_id: list[str] | None = Query(
        default=None,
        description="Optional rule id(s); omit to evaluate all enabled rules",
    ),
    include_disabled: bool = Query(default=False),
    engine: RuleEngine | None = Depends(get_rule_engine),
    config=Depends(get_config),
) -> RuleEvaluateResponse:
    """Evaluate engineering rules against the knowledge graph (and case index)."""
    product, project, build = resolve_request_scope(config, product, project, build)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Rules engine unavailable. Ensure rules.enabled is true, "
                "config/rules/ exists, and the knowledge graph is built "
                "(python scripts/build_graph.py)."
            ),
        )
    summary = engine.evaluate_summary(
        rule_ids=rule_id,
        product=product,
        project=project,
        build=build,
        include_disabled=include_disabled,
    )
    return RuleEvaluateResponse(
        product=product,
        project=project,
        build=build,
        pack_dir=str(summary.get("pack_dir", "")),
        counts=dict(summary.get("counts") or {}),
        results=[
            RuleResultModel(**item)
            for item in (summary.get("results") or [])
            if isinstance(item, dict)
        ],
        limitations=str(summary.get("limitations", "")),
    )
