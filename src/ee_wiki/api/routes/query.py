"""Explicit RAG query route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ee_wiki.api.deps import get_rag_service
from ee_wiki.api.models import CitationModel, QueryRequest, QueryResponse
from ee_wiki.generation.service import RagService

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    service: RagService = Depends(get_rag_service),
) -> QueryResponse:
    """Run retrieval + generation and return answer with citations."""
    result = service.answer(
        body.query,
        target_project=body.project,
        target_build=body.build,
        document_type=body.document_type,
        top_k_final=body.top_k,
    )
    return QueryResponse(
        answer=result.answer,
        insufficient_context=result.insufficient_context,
        citations=[
            CitationModel(
                source_file=citation.source_file,
                chunk_id=citation.chunk_id,
                page=citation.page,
                excerpt=citation.excerpt,
            )
            for citation in result.citations
        ],
    )
