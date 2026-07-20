"""Debug-case lookup route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ee_wiki.api.deps import get_config, get_rag_service
from ee_wiki.api.models import CaseHitModel, CaseSearchResponse
from ee_wiki.api.scope_params import resolve_request_scope
from ee_wiki.generation.service import RagService

router = APIRouter(prefix="/v1", tags=["cases"])


@router.get("/cases/search", response_model=CaseSearchResponse)
async def search_cases(
    q: str = Query(..., min_length=1, description="Symptom, part, net, or case id"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    service: RagService = Depends(get_rag_service),
    config=Depends(get_config),
) -> CaseSearchResponse:
    """Search the debug-case index for matching FA / debug cases."""
    product, project, build = resolve_request_scope(config, product, project, build)
    hits = service.engine.search_cases(
        q,
        target_product=product,
        target_project=project,
        target_build=build,
        limit=limit,
    )
    return CaseSearchResponse(
        query=q,
        hits=[
            CaseHitModel(
                case_id=hit.case_id,
                product=hit.product,
                project=hit.project,
                build=hit.build,
                title=hit.title,
                source_file=hit.source_file,
                document_type=hit.document_type,
                symptom=hit.symptom,
                suspected_nets=list(hit.suspected_nets),
                suspected_parts=list(hit.suspected_parts),
                steps=list(hit.steps),
                root_cause=hit.root_cause,
                case_citations=list(hit.case_citations),
                keywords=list(hit.keywords),
                chunk_ids=list(hit.chunk_ids),
            )
            for hit in hits
        ],
    )
