"""Index project inventory route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ee_wiki.api.deps import get_rag_service
from ee_wiki.api.models import ProjectInventoryEntryModel, ProjectInventoryResponse
from ee_wiki.generation.service import RagService

router = APIRouter(prefix="/v1", tags=["projects"])


@router.get("/projects", response_model=ProjectInventoryResponse)
async def list_projects(
    service: RagService = Depends(get_rag_service),
) -> ProjectInventoryResponse:
    """Return indexed project/build inventory from the loaded hybrid index."""
    inventory = service.engine.get_index_inventory()
    return ProjectInventoryResponse(
        chunk_count=inventory.chunk_count,
        product_count=inventory.product_count,
        enterprise_project=inventory.enterprise_project,
        project_shared_build=inventory.project_shared_build,
        projects=[
            ProjectInventoryEntryModel(
                product=entry.product,
                project=entry.project,
                builds=list(entry.builds),
                chunk_count=entry.chunk_count,
                is_enterprise=entry.is_enterprise,
            )
            for entry in inventory.projects
        ],
    )
