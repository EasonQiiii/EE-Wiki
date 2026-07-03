"""Explicit RAG query route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ee_wiki.api.citation_models import citation_to_model
from ee_wiki.api.concurrency import queue_response_headers
from ee_wiki.api.deps import get_config, get_queue_gate, get_rag_service
from ee_wiki.api.models import QueryRequest, QueryResponse
from ee_wiki.api.rag_handler import rag_request_slot
from ee_wiki.api.timeout import (
    RequestTimeoutError,
    raise_request_timeout_http_error,
    run_sync_with_request_timeout,
)
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.llm.errors import LlmTimeoutError
from ee_wiki.generation.service import RagService

router = APIRouter(prefix="/v1", tags=["query"])
logger = get_logger(__name__)


@router.post("/query", response_model=QueryResponse)
async def query(
    body: QueryRequest,
    response: Response,
    service: RagService = Depends(get_rag_service),
    gate=Depends(get_queue_gate),
    config=Depends(get_config),
) -> QueryResponse:
    """Run retrieval + generation and return answer with citations."""
    with rag_request_slot(gate) as snapshot:
        response.headers.update(queue_response_headers(snapshot))
        try:
            result = await run_sync_with_request_timeout(
                service.answer,
                body.query,
                timeout_seconds=config.api.request_timeout_seconds,
                target_project=body.project,
                target_build=body.build,
                document_type=body.document_type,
                top_k_final=body.top_k,
                task=body.task,
            )
        except (RequestTimeoutError, LlmTimeoutError) as exc:
            logger.error("Query timed out: %s", exc)
            raise raise_request_timeout_http_error(exc) from exc
    return QueryResponse(
        answer=result.answer,
        insufficient_context=result.insufficient_context,
        citations=[citation_to_model(citation) for citation in result.citations],
    )
