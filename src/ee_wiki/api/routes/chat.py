"""OpenAI-compatible chat completion route."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from ee_wiki.api.deps import get_rag_service
from ee_wiki.api.models import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CitationModel,
)
from ee_wiki.generation.service import RagService

router = APIRouter(prefix="/v1", tags=["chat"])


def _extract_user_question(messages: list) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    raise HTTPException(status_code=400, detail="No user message found in messages")


@router.post("/chat/completions", response_model=ChatCompletionResponse)
def chat_completions(
    body: ChatCompletionRequest,
    service: RagService = Depends(get_rag_service),
) -> ChatCompletionResponse:
    """Run RAG using the last user message as the query."""
    question = _extract_user_question(body.messages)
    result = service.answer(
        question,
        target_project=body.project,
        target_build=body.build,
        document_type=body.document_type,
        top_k_final=body.top_k,
    )
    return ChatCompletionResponse(
        id=f"chatcmpl-{uuid.uuid4().hex}",
        model=body.model,
        choices=[
            ChatChoice(
                message=ChatChoiceMessage(content=result.answer),
            )
        ],
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
