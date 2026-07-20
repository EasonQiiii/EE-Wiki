"""Component lookup route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ee_wiki.api.deps import get_config, get_rag_service
from ee_wiki.api.models import ComponentHitModel, ComponentSearchResponse
from ee_wiki.api.scope_params import resolve_request_scope
from ee_wiki.generation.service import RagService

router = APIRouter(prefix="/v1", tags=["components"])


@router.get("/components/search", response_model=ComponentSearchResponse)
async def search_components(
    q: str = Query(..., min_length=1, description="Part number or schematic designator"),
    product: str | None = Query(default=None),
    project: str | None = Query(default=None),
    build: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    service: RagService = Depends(get_rag_service),
    config=Depends(get_config),
) -> ComponentSearchResponse:
    """Search the component index for matching chunks."""
    product, project, build = resolve_request_scope(config, product, project, build)
    hits = service.engine.search_components(
        q,
        target_product=product,
        target_project=project,
        target_build=build,
        limit=limit,
    )
    return ComponentSearchResponse(
        query=q,
        hits=[
            ComponentHitModel(
                key=hit.key,
                kind=hit.kind,
                chunk_id=hit.chunk_id,
                product=hit.product,
                project=hit.project,
                build=hit.build,
                document_type=hit.document_type,
                source_file=hit.source_file,
                page=hit.page,
                title=hit.title,
                excerpt=hit.excerpt,
            )
            for hit in hits
        ],
    )
