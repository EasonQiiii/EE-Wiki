"""Explicit RAG query route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ee_wiki.api.citation_models import citation_to_model
from ee_wiki.api.concurrency import queue_response_headers
from ee_wiki.api.deps import get_queue_gate, get_rag_service
from ee_wiki.api.models import QueryRequest, QueryResponse
from ee_wiki.api.rag_handler import rag_request_slot
from ee_wiki.generation.service import RagService

router = APIRouter(prefix="/v1", tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    response: Response,
    service: RagService = Depends(get_rag_service),
    gate=Depends(get_queue_gate),
) -> QueryResponse:
    """Run retrieval + generation and return answer with citations."""
    with rag_request_slot(gate) as snapshot:
        response.headers.update(queue_response_headers(snapshot))
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
        citations=[citation_to_model(citation) for citation in result.citations],
    )
