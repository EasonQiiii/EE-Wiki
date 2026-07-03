"""OpenAI-compatible chat completion route."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ee_wiki.api.cancel import start_disconnect_watcher
from ee_wiki.api.citation_models import citation_to_model
from ee_wiki.api.concurrency import QueueFullError, queue_response_headers
from ee_wiki.api.deps import get_config, get_queue_gate, get_rag_service
from ee_wiki.api.models import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CitationModel,
)
from ee_wiki.api.open_webui_sources import citations_to_open_webui_sources
from ee_wiki.api.rag_handler import rag_request_slot, raise_queue_full_http_error
from ee_wiki.api.stream_cancel import iter_sync_text_chunks
from ee_wiki.api.timeout import (
    REQUEST_TIMEOUT_MESSAGE,
    RequestTimeoutError,
    raise_request_timeout_http_error,
    run_sync_with_request_timeout,
)
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.llm.errors import LlmLoadError, LlmTimeoutError
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
    sources: list[dict[str, object]],
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
        sources=sources,
        insufficient_context=insufficient_context,
    )


def _sse_chunk(
    *,
    chat_id: str,
    model: str,
    created: int,
    delta: dict[str, str],
    finish_reason: str | None = None,
    sources: list[dict[str, object]] | None = None,
) -> str:
    payload: dict[str, object] = {
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
    if sources:
        payload["sources"] = sources
        payload["event"] = {
            "type": "chat:completion",
            "data": {"sources": sources},
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
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    response: Response,
    service: RagService = Depends(get_rag_service),
    gate=Depends(get_queue_gate),
    config=Depends(get_config),
):
    """Run RAG using the last user message as the query."""
    question = _extract_user_question(body.messages)
    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    request_timeout = config.api.request_timeout_seconds

    if body.stream:
        try:
            slot_ctx = gate.slot()
            snapshot = slot_ctx.__enter__()
        except QueueFullError as exc:
            raise raise_queue_full_http_error(exc) from exc

        async def wrapped_stream() -> AsyncIterator[str]:
            try:
                async for chunk in _stream_answer(
                    request=request,
                    service=service,
                    chat_id=chat_id,
                    created=created,
                    model=body.model,
                    question=question,
                    project=body.project,
                    build=body.build,
                    document_type=body.document_type,
                    top_k=body.top_k,
                    task=body.task,
                    request_timeout_seconds=request_timeout,
                ):
                    yield chunk
            finally:
                slot_ctx.__exit__(None, None, None)

        return StreamingResponse(
            wrapped_stream(),
            media_type="text/event-stream",
            headers=queue_response_headers(snapshot),
        )

    cancel = threading.Event()
    watcher = start_disconnect_watcher(
        request,
        cancel,
        label=f"Chat completion {chat_id}",
    )
    try:
        with rag_request_slot(gate) as snapshot:
            response.headers.update(queue_response_headers(snapshot))
            try:
                stream_result = await run_sync_with_request_timeout(
                    service.stream_answer,
                    question,
                    timeout_seconds=request_timeout,
                    target_project=body.project,
                    target_build=body.build,
                    document_type=body.document_type,
                    top_k_final=body.top_k,
                    cancel_event=cancel,
                    task=body.task,
                )
            except (RequestTimeoutError, LlmTimeoutError) as exc:
                logger.error("Chat completion %s timed out: %s", chat_id, exc)
                raise raise_request_timeout_http_error(exc) from exc
            except LlmLoadError as exc:
                logger.error("LLM load failed: %s", exc)
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            if cancel.is_set():
                logger.info("Chat completion %s cancelled after retrieval", chat_id)
                return Response(status_code=204)

            fragments: list[str] = []
            try:
                async for fragment in iter_sync_text_chunks(
                    stream_result.text_chunks,
                    cancel=cancel,
                    request=request,
                ):
                    if cancel.is_set():
                        logger.info(
                            "Chat completion %s cancelled during generation",
                            chat_id,
                        )
                        return Response(status_code=204)
                    fragments.append(fragment)
            except LlmTimeoutError as exc:
                logger.error("Chat completion %s timed out: %s", chat_id, exc)
                raise raise_request_timeout_http_error(exc) from exc

            if cancel.is_set():
                return Response(status_code=204)

            content = "".join(fragments).strip() or INSUFFICIENT_ANSWER
            citation_models = [citation_to_model(citation) for citation in stream_result.citations]
            sources = citations_to_open_webui_sources(stream_result.citations)
            logger.info(
                "Chat completion %s finished (%d chars, insufficient=%s)",
                chat_id,
                len(content),
                not fragments,
            )
            return _build_response(
                chat_id=chat_id,
                model=body.model,
                content=content,
                citations=citation_models,
                sources=sources,
                insufficient_context=content == INSUFFICIENT_ANSWER and not stream_result.citations,
            )
    finally:
        watcher.cancel()


async def _stream_answer(
    *,
    request: Request,
    service: RagService,
    chat_id: str,
    created: int,
    model: str,
    question: str,
    project: str | None,
    build: str | None,
    document_type: str | None,
    top_k: int | None,
    task: str | None,
    request_timeout_seconds: float | None,
) -> AsyncIterator[str]:
    """Yield OpenAI-compatible SSE chunks for a streamed RAG answer."""
    cancel = threading.Event()
    watcher = start_disconnect_watcher(request, cancel, label=f"Chat stream {chat_id}")
    fragments: list[str] = []
    deadline = (
        time.monotonic() + request_timeout_seconds
        if request_timeout_seconds and request_timeout_seconds > 0
        else None
    )

    def _timed_out() -> bool:
        return deadline is not None and time.monotonic() > deadline

    try:
        yield _sse_chunk(
            chat_id=chat_id,
            model=model,
            created=created,
            delta={"role": "assistant"},
        )

        if _timed_out():
            raise RequestTimeoutError("Request timed out before retrieval")

        remaining_timeout = None
        if deadline is not None:
            remaining_timeout = deadline - time.monotonic()
            if remaining_timeout <= 0:
                raise RequestTimeoutError("Request timed out before retrieval")

        stream_result = await run_sync_with_request_timeout(
            service.stream_answer,
            question,
            timeout_seconds=remaining_timeout,
            target_project=project,
            target_build=build,
            document_type=document_type,
            top_k_final=top_k,
            cancel_event=cancel,
            task=task,
        )
        if cancel.is_set():
            logger.info("Chat stream %s cancelled before generation", chat_id)
            return

        sources = citations_to_open_webui_sources(stream_result.citations)
        if sources:
            yield _sse_chunk(
                chat_id=chat_id,
                model=model,
                created=created,
                delta={},
                sources=sources,
            )

        async for fragment in iter_sync_text_chunks(
            stream_result.text_chunks,
            cancel=cancel,
            request=request,
        ):
            if _timed_out():
                raise RequestTimeoutError("Request timed out during streaming")
            fragments.append(fragment)
            yield _sse_chunk(
                chat_id=chat_id,
                model=model,
                created=created,
                delta={"content": fragment},
            )

        if cancel.is_set():
            logger.info("Chat stream %s cancelled (%d chars partial)", chat_id, len(fragments))
            return

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
    except (RequestTimeoutError, LlmTimeoutError) as exc:
        logger.error("Chat stream %s timed out: %s", chat_id, exc)
        yield _sse_chunk(
            chat_id=chat_id,
            model=model,
            created=created,
            delta={"content": f"\n\n{REQUEST_TIMEOUT_MESSAGE}"},
        )
        yield _sse_chunk(
            chat_id=chat_id,
            model=model,
            created=created,
            delta={},
            finish_reason="stop",
        )
        yield "data: [DONE]\n\n"
    finally:
        watcher.cancel()
