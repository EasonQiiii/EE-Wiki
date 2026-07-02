"""OpenAI-compatible chat completion route."""

from __future__ import annotations

import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from ee_wiki.api.deps import get_rag_service
from ee_wiki.api.models import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CitationModel,
)
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.llm.local import LlmLoadError
from ee_wiki.generation.service import INSUFFICIENT_ANSWER, RagService

router = APIRouter(prefix="/v1", tags=["chat"])
logger = get_logger(__name__)


def _extract_user_question(messages: list) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    raise HTTPException(status_code=400, detail="No user message found in messages")


def _build_response(
    *,
    chat_id: str,
    model: str,
    content: str,
    citations: list[CitationModel],
    insufficient_context: bool,
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id=chat_id,
        created=int(time.time()),
        model=model,
        choices=[
            ChatChoice(
                message=ChatChoiceMessage(content=content),
            )
        ],
        citations=citations,
        insufficient_context=insufficient_context,
    )


def _sse_chunk(
    *,
    chat_id: str,
    model: str,
    created: int,
    delta: dict[str, str],
    finish_reason: str | None = None,
) -> str:
    payload = {
        "id": chat_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.get("/models")
def list_models() -> dict:
    """Return a minimal OpenAI-compatible model list for Open WebUI."""
    return {
        "object": "list",
        "data": [
            {
                "id": "ee-wiki",
                "object": "model",
                "owned_by": "ee-wiki",
            }
        ],
    }


@router.post("/chat/completions")
def chat_completions(
    body: ChatCompletionRequest,
    service: RagService = Depends(get_rag_service),
):
    """Run RAG using the last user message as the query."""
    question = _extract_user_question(body.messages)
    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())

    if body.stream:
        return StreamingResponse(
            _stream_answer(
                service=service,
                chat_id=chat_id,
                created=created,
                model=body.model,
                question=question,
                project=body.project,
                build=body.build,
                document_type=body.document_type,
                top_k=body.top_k,
            ),
            media_type="text/event-stream",
        )

    try:
        result = service.answer(
            question,
            target_project=body.project,
            target_build=body.build,
            document_type=body.document_type,
            top_k_final=body.top_k,
        )
    except LlmLoadError as exc:
        logger.error("LLM load failed: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    content = result.answer or INSUFFICIENT_ANSWER
    logger.info(
        "Chat completion %s finished (%d chars, insufficient=%s)",
        chat_id,
        len(content),
        result.insufficient_context,
    )
    return _build_response(
        chat_id=chat_id,
        model=body.model,
        content=content,
        citations=[
            CitationModel(
                source_file=citation.source_file,
                chunk_id=citation.chunk_id,
                page=citation.page,
                excerpt=citation.excerpt,
            )
            for citation in result.citations
        ],
        insufficient_context=result.insufficient_context,
    )


def _stream_answer(
    *,
    service: RagService,
    chat_id: str,
    created: int,
    model: str,
    question: str,
    project: str | None,
    build: str | None,
    document_type: str | None,
    top_k: int | None,
):
    """Yield OpenAI-compatible SSE chunks for a streamed RAG answer."""
    yield _sse_chunk(
        chat_id=chat_id,
        model=model,
        created=created,
        delta={"role": "assistant"},
    )

    fragments: list[str] = []
    for fragment in service.answer_stream(
        question,
        target_project=project,
        target_build=build,
        document_type=document_type,
        top_k_final=top_k,
    ):
        fragments.append(fragment)
        yield _sse_chunk(
            chat_id=chat_id,
            model=model,
            created=created,
            delta={"content": fragment},
        )

    content = "".join(fragments).strip() or INSUFFICIENT_ANSWER
    logger.info("Chat stream %s finished (%d chars)", chat_id, len(content))
    yield _sse_chunk(
        chat_id=chat_id,
        model=model,
        created=created,
        delta={},
        finish_reason="stop",
    )
    yield "data: [DONE]\n\n"
