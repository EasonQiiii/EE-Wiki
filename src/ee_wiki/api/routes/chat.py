"""OpenAI-compatible chat completion route."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ee_wiki.api.cancel import start_disconnect_watcher
from ee_wiki.api.chat_pipeline import (
    RequestTrace,
    scope_source_label,
)
from ee_wiki.api.citation_models import citation_to_model
from ee_wiki.api.concurrency import QueueFullError, queue_response_headers
from ee_wiki.api.deps import (
    get_config,
    get_connectivity_query,
    get_queue_gate,
    get_rag_service,
)
from ee_wiki.api.models import (
    ChatChoice,
    ChatChoiceMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    CitationModel,
)
from ee_wiki.api.open_webui_auxiliary import (
    AUXILIARY_MAX_NEW_TOKENS,
    is_open_webui_auxiliary_task,
)
from ee_wiki.api.open_webui_sources import citations_to_open_webui_sources
from ee_wiki.api.rag_handler import raise_queue_full_http_error
from ee_wiki.api.scope_marker import (
    CarriedScope,
    format_scope_marker,
    parse_scope_marker,
)
from ee_wiki.api.scope_params import resolve_request_scope
from ee_wiki.api.stream_cancel import iter_sync_text_chunks
from ee_wiki.api.stream_status import (
    GENERATION_STATUS,
    RETRIEVAL_STATUS,
    clear_status_chunk,
    format_status_chunk,
)
from ee_wiki.api.timeout import (
    REQUEST_TIMEOUT_MESSAGE,
    RequestTimeoutError,
    raise_request_timeout_http_error,
    run_sync_with_request_timeout,
)
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.connectivity.query import ConnectivityQuery
from ee_wiki.generation.citations import (
    StreamingCitationMarkerRemapper,
    compact_citations,
    remap_citation_markers,
)
from ee_wiki.generation.elapsed import RagPhaseTiming, format_phase_timing_footer
from ee_wiki.generation.inline_images import build_image_block
from ee_wiki.generation.llm.errors import LlmLoadError, LlmTimeoutError
from ee_wiki.generation.service import INSUFFICIENT_ANSWER, AnswerStreamResult, RagService
from ee_wiki.integrations.fa_errors import format_fa_error
from ee_wiki.retrieval.rewrite import ConversationTurn

router = APIRouter(prefix="/v1", tags=["chat"])
logger = get_logger(__name__)

# Strips any echoed scope marker so _emit appends exactly one (a tool/LLM may
# copy the invisible `<!-- ee-wiki-scope: -->` comment into its output).
_SCOPE_MARKER_STRIP_RE = re.compile(r"<!--\s*ee-wiki-scope:[^>]*-->")


def _extract_user_question(messages: list) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    raise HTTPException(status_code=400, detail="No user message found in messages")


def _extract_history(messages: list) -> list[ConversationTurn]:
    """Extract conversation history (all turns before the last user message).

    Args:
        messages: Full message list from the request.

    Returns:
        Prior turns as ConversationTurn objects, excluding the final user message.
    """
    last_user_idx = -1
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user" and messages[i].content.strip():
            last_user_idx = i
            break
    if last_user_idx <= 0:
        return []
    turns: list[ConversationTurn] = []
    for msg in messages[:last_user_idx]:
        if msg.role in ("user", "assistant") and msg.content.strip():
            turns.append(ConversationTurn(role=msg.role, content=msg.content.strip()))
    return turns


def _should_bypass_rag(question: str) -> bool:
    """Return whether to skip hybrid retrieval for this chat request."""
    return is_open_webui_auxiliary_task(question)


def _fetch_stream_result(
    service: RagService,
    question: str,
    *,
    bypass_rag: bool,
    target_product: str | None,
    target_project: str | None,
    target_build: str | None,
    document_type: str | None,
    top_k: int | None,
    cancel_event: threading.Event | None,
    task: str | None,
    history: list[ConversationTurn] | None,
    connectivity_query: ConnectivityQuery | None = None,
    conversation_id: str | None = None,
) -> AnswerStreamResult:
    """Run gates, supervisor intent, then hybrid RAG (ADR 0012)."""
    if bypass_rag:
        logger.info(
            "Open WebUI auxiliary task — bypassing RAG (%d prompt chars)",
            len(question),
        )
        return service.stream_direct(
            question,
            cancel_event=cancel_event,
            max_new_tokens=AUXILIARY_MAX_NEW_TOKENS,
        )

    trace = RequestTrace(
        scope_source=scope_source_label(
            product=target_product,
            project=target_project,
            build=target_build,
        ),
    )

    # Open WebUI rarely sends body.product/project/build. Lock TurnScope once
    # here (ADR 0012 §6) before connectivity / FA / Supervisor / tools.
    # Downstream must not re-infer conflicting product/project/build.
    if not (target_product and target_project and target_build):
        from ee_wiki.retrieval.scope_from_question import merge_scope_from_question

        target_product, target_project, target_build = merge_scope_from_question(
            question,
            config=service.config,
            engine=getattr(service, "engine", None),
            product=target_product,
            project=target_project,
            build=target_build,
        )
        trace.scope_source = scope_source_label(
            product=target_product,
            project=target_project,
            build=target_build,
        )

    # Cross-turn scope carry via a history-embedded marker (ADR 0012 §6,
    # multi-worker safe). Instead of a per-process memory store (which drops the
    # carry when consecutive turns hit different uvicorn workers), the locked
    # (product, project, build) is embedded as a hidden HTML comment in the
    # assistant reply and recovered from `history` next turn. Explicit
    # body/question scope already won above; the carry only backfills axes the
    # new question left blank. No NL re-inference, no shared state. The carry is
    # driven by `history` (the prior turns Open WebUI echoes back), NOT by
    # `conversation_id` — Open WebUI's standard OpenAI-compatible
    # /v1/chat/completions request does not send `conversation_id`, so gating on
    # it would silently disable carry in production. Both steps are gated by
    # `carry_scope_across_turns`.
    if service.config.api.carry_scope_across_turns and history:
        carried = parse_scope_marker(history)
        if carried is not None:
            if not target_product and carried.product:
                target_product = carried.product
            if not target_project and carried.project:
                target_project = carried.project
            if not target_build and carried.build:
                target_build = carried.build
            if target_product or target_project or target_build:
                trace.scope_source = scope_source_label(
                    product=target_product,
                    project=target_project,
                    build=target_build,
                    carried=True,
                )

    # Prepare this turn's scope marker. It is a hidden comment appended to the
    # assistant reply (see `_emit`) so the next turn can recover it from history.
    # Only emitted when carrying is enabled, a conversation id exists, and the
    # locked scope is non-empty. `_emit` attaches it to every answer branch
    # uniformly, so connectivity / FA / supervisor / hybrid answers all carry it.
    _scope_marker: str | None = None
    if service.config.api.carry_scope_across_turns:
        _locked = CarriedScope(target_product, target_project, target_build)
        if not _locked.empty:
            _scope_marker = format_scope_marker(
                target_product, target_project, target_build
            )

    def _emit(text_chunks: Iterator[str], *, citations: list) -> AnswerStreamResult:
        if not _scope_marker:
            return AnswerStreamResult(citations=list(citations), text_chunks=text_chunks)

        def _stream() -> Iterator[str]:
            for chunk in text_chunks:
                # Strip any echoed marker (a tool/LLM may copy the invisible
                # comment) so we append exactly one at the end.
                yield _SCOPE_MARKER_STRIP_RE.sub("", chunk)
            yield _scope_marker

        return AnswerStreamResult(citations=list(citations), text_chunks=_stream())

    # Authoritative connectivity gate (ADR 0009): trace questions must return
    # gated pin tables or an explicit refusal — never hybrid-RAG prose that
    # invents 起点→终点 paths from VLM/OCR text.
    conn_cfg = getattr(
        getattr(service.config, "schematic_pdf", None), "connectivity", None
    )
    if conn_cfg is not None and getattr(conn_cfg, "enabled", False):
        from ee_wiki.connectivity.chat import answer_trace_question

        trace_md = answer_trace_question(
            question,
            cq=connectivity_query,
            connectivity_enabled=True,
            product=target_product,
            project=target_project,
            build=target_build,
        )
        if trace_md is not None:
            trace.gate = "connectivity_authority"
            trace.branch = "respond"
            trace.task_owner = "connectivity"
            trace.task = "trace"
            trace.log()
            return _emit(iter([trace_md]), citations=[])

    routed_task = task
    agent_evidence: str | None = None
    task_owner = "legacy"
    agents_cfg = getattr(service.config, "agents", None)

    # FA mode gate (fa-session.md A/B/C): runs before the Wiki Supervisor so an
    # FA-intent turn (with or without a Radar id) never silently falls through
    # to hybrid RAG. When fa.enabled and mode == "fa", route to FaAgent.
    # Use ``is True`` so a bare-MagicMock test service (where service.config is
    # not a real bool) cannot accidentally enter the LLM path — mirrors the
    # supervisor guard below.
    mode = "wiki"
    if service.config.fa.enabled is True and not bypass_rag:
        from ee_wiki.agents.fa_mode import resolve_chat_mode

        mode = resolve_chat_mode(
            question,
            history,
            llm=service.llm,
            config=service.config,
            cancel_event=cancel_event,
        )
    trace.mode = mode

    if service.config.fa.enabled is True and mode == "fa":
        from ee_wiki.agents.fa_agent import FaAgentResult, open_fa_agent
        from ee_wiki.tools.context import ToolContext

        fa_ctx = ToolContext(config=service.config, engine=service.engine)
        fa_ctx.llm = service.llm
        fa_agent = open_fa_agent(service.config, tool_context=fa_ctx, llm=service.llm)
        try:
            fa_result = fa_agent.handle(
                question,
                product=target_product,
                project=target_project,
                build=target_build,
                history=history,
                cancel_event=cancel_event,
            )
        except EEWikiError as exc:
            # Radar integration failure (no Kerberos, ACL/403, ticket missing,
            # attachment download). Surface a friendly Chinese reply instead of
            # letting the exception escape to an HTTP 500. Details are logged.
            logger.warning("FA agent error; returning friendly message", exc_info=True)
            fa_result = FaAgentResult(
                markdown=format_fa_error(exc),
                citations=[],
                routed_skills=(),
                branch="fa_agent_error",
            )
        trace.gate = "fa_mode"
        trace.branch = fa_result.branch
        trace.task_owner = "fa_agent"
        trace.task = "fa"
        trace.roles = fa_result.routed_skills
        trace.log()
        return _emit(iter([fa_result.markdown]), citations=fa_result.citations)

    # V4 supervisor path (ADR 0008 / 0012). Require real bool True so MagicMock
    # configs in unit tests fall through to legacy RAG.
    if agents_cfg is not None and agents_cfg.enabled is True:
        from ee_wiki.agents.supervisor import open_supervisor
        from ee_wiki.tools.context import ToolContext

        tool_ctx = ToolContext(config=service.config, engine=service.engine)
        tool_ctx.llm = service.llm
        supervisor = open_supervisor(
            service.config,
            tool_context=tool_ctx,
            connectivity_query=connectivity_query,
            llm=service.llm,
        )
        route_started = time.monotonic()
        result = supervisor.handle(
            question,
            product=target_product,
            project=target_project,
            build=target_build,
            history=history,
            requested_task=task,
            cancel_event=cancel_event,
        )
        trace.mark_phase("route_tools", route_started)
        trace.route_mode = supervisor.last_route_mode
        trace.llm_calls = supervisor.last_llm_calls
        trace.roles = result.roles_used
        routed_task = task or result.task
        task_owner = "supervisor"
        trace.task_owner = "supervisor"
        trace.task = routed_task

        if result.kind in ("clarify", "respond"):
            trace.branch = result.kind
            trace.log()
            return _emit(iter([result.markdown]), citations=[])

        if result.kind == "hybrid":
            agent_evidence = result.markdown or None
            trace.branch = "hybrid"
            logger.info(
                "Supervisor hybrid — RAG with evidence (%d chars, roles=%s)",
                len(result.markdown),
                result.roles_used,
            )
        else:
            # passthrough (and any unexpected kind) → plain hybrid RAG
            trace.branch = "passthrough"
            logger.info(
                "Supervisor passthrough — hybrid RAG (task=%s)",
                routed_task,
            )
    else:
        trace.task_owner = "legacy"
        trace.task = routed_task
        trace.branch = "passthrough"

    stream = service.stream_answer(
        question,
        target_product=target_product,
        target_project=target_project,
        target_build=target_build,
        document_type=document_type,
        top_k_final=top_k,
        cancel_event=cancel_event,
        task=routed_task,
        history=history,
        agent_evidence=agent_evidence,
        task_owner=task_owner,
    )
    if agent_evidence and not stream.citations:
        trace.evidence_only = True
    trace.log()
    return _emit(stream.text_chunks, citations=stream.citations)


def _elapsed_footer(
    *,
    timing: RagPhaseTiming | None,
    show_elapsed_time: bool,
    bypass_rag: bool,
) -> str | None:
    """Return phase timing footer text when enabled for RAG answers."""
    if not show_elapsed_time or bypass_rag or timing is None:
        return None
    return format_phase_timing_footer(timing)


def _build_phase_timing(
    *,
    started: float,
    retrieval_done_at: float | None,
    first_char_at: float | None,
) -> RagPhaseTiming | None:
    """Build phase timings from monotonic checkpoints."""
    if retrieval_done_at is None:
        return None
    retrieval_seconds = retrieval_done_at - started
    if first_char_at is None:
        return RagPhaseTiming(
            retrieval_seconds=retrieval_seconds,
            generation_seconds=0.0,
            first_char_seconds=retrieval_seconds,
        )
    return RagPhaseTiming(
        retrieval_seconds=retrieval_seconds,
        generation_seconds=first_char_at - retrieval_done_at,
        first_char_seconds=first_char_at - started,
    )


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
    connectivity_query: ConnectivityQuery | None = Depends(get_connectivity_query),
):
    """Run RAG using the last user message as the query."""
    question = _extract_user_question(body.messages)
    history = _extract_history(body.messages)
    bypass_rag = _should_bypass_rag(question)
    product, project, build = resolve_request_scope(
        config, body.product, body.project, body.build
    )
    chat_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    request_started = time.monotonic()
    request_timeout = config.api.request_timeout_seconds
    show_elapsed_time = config.generation.show_elapsed_time
    request_deadline = (
        request_started + request_timeout
        if request_timeout and request_timeout > 0
        else None
    )

    if body.stream:
        slot_ctx = gate.slot()
        try:
            snapshot = await asyncio.to_thread(slot_ctx.__enter__)
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
                    product=product,
                    project=project,
                    build=build,
                    document_type=body.document_type,
                    top_k=body.top_k,
                    task=body.task,
                    request_timeout_seconds=request_timeout,
                    history=history,
                    bypass_rag=bypass_rag,
                    request_started=request_started,
                    show_elapsed_time=show_elapsed_time,
                    connectivity_query=connectivity_query,
                    conversation_id=body.conversation_id,
                ):
                    yield chunk
            finally:
                await asyncio.to_thread(slot_ctx.__exit__, None, None, None)

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
        slot_ctx = gate.slot()
        try:
            snapshot = await asyncio.to_thread(slot_ctx.__enter__)
        except QueueFullError as exc:
            raise raise_queue_full_http_error(exc) from exc
        try:
            response.headers.update(queue_response_headers(snapshot))
            remaining_timeout = None
            if request_deadline is not None:
                remaining_timeout = request_deadline - time.monotonic()
                if remaining_timeout <= 0:
                    raise RequestTimeoutError("Request timed out before retrieval")
            try:
                stream_result = await run_sync_with_request_timeout(
                    _fetch_stream_result,
                    service,
                    question,
                    bypass_rag=bypass_rag,
                    target_product=product,
                    target_project=project,
                    target_build=build,
                    document_type=body.document_type,
                    top_k=body.top_k,
                    cancel_event=cancel,
                    task=body.task,
                    history=history,
                    connectivity_query=connectivity_query,
                    conversation_id=body.conversation_id,
                    timeout_seconds=remaining_timeout,
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

            retrieval_done_at = time.monotonic()
            if request_deadline is not None:
                remaining_timeout = request_deadline - time.monotonic()
                if remaining_timeout <= 0:
                    raise RequestTimeoutError("Request timed out before generation")
            fragments: list[str] = []
            first_char_at: float | None = None
            try:
                async for fragment in iter_sync_text_chunks(
                    stream_result.text_chunks,
                    cancel=cancel,
                    request=request,
                    timeout_seconds=remaining_timeout,
                ):
                    if cancel.is_set():
                        logger.info(
                            "Chat completion %s cancelled during generation",
                            chat_id,
                        )
                        return Response(status_code=204)
                    if first_char_at is None:
                        first_char_at = time.monotonic()
                    fragments.append(fragment)
            except (RequestTimeoutError, LlmTimeoutError) as exc:
                logger.error("Chat completion %s timed out: %s", chat_id, exc)
                raise raise_request_timeout_http_error(exc) from exc

            if cancel.is_set():
                return Response(status_code=204)

            content = "".join(fragments).strip() or INSUFFICIENT_ANSWER
            # Compact duplicate citations (same document) and remap the LLM's
            # dense [N] markers so Open WebUI's sources stay 1:1 with the text.
            _compacted, _marker_map = compact_citations(stream_result.citations)
            content = remap_citation_markers(content, _marker_map)
            citation_models = [citation_to_model(citation) for citation in _compacted]
            sources = citations_to_open_webui_sources(_compacted)
            insufficient = content == INSUFFICIENT_ANSWER and not stream_result.citations
            try:
                if config.generation.inline_citation_images and not insufficient:
                    image_block = build_image_block(
                        content,
                        stream_result.citations,
                        max_images=config.generation.max_inline_images,
                    )
                    if image_block:
                        content = content.rstrip() + image_block
            except (AttributeError, TypeError):
                pass
            footer = _elapsed_footer(
                timing=_build_phase_timing(
                    started=request_started,
                    retrieval_done_at=retrieval_done_at,
                    first_char_at=first_char_at,
                ),
                show_elapsed_time=show_elapsed_time,
                bypass_rag=bypass_rag,
            )
            if footer:
                content = content.rstrip() + footer
            phase_timing = _build_phase_timing(
                started=request_started,
                retrieval_done_at=retrieval_done_at,
                first_char_at=first_char_at,
            )
            logger.info(
                "Chat completion %s finished (%d chars, insufficient=%s, "
                "retrieval=%.1fs, generation=%.1fs, first_char=%.1fs)",
                chat_id,
                len(content),
                not fragments,
                phase_timing.retrieval_seconds if phase_timing else 0.0,
                phase_timing.generation_seconds if phase_timing else 0.0,
                phase_timing.first_char_seconds if phase_timing else 0.0,
            )
            return _build_response(
                chat_id=chat_id,
                model=body.model,
                content=content,
                citations=citation_models,
                sources=sources,
                insufficient_context=insufficient,
            )
        finally:
            await asyncio.to_thread(slot_ctx.__exit__, None, None, None)
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
    product: str | None,
    project: str | None,
    build: str | None,
    document_type: str | None,
    top_k: int | None,
    task: str | None,
    request_timeout_seconds: float | None,
    history: list[ConversationTurn] | None = None,
    bypass_rag: bool = False,
    request_started: float | None = None,
    show_elapsed_time: bool = False,
    connectivity_query: ConnectivityQuery | None = None,
    conversation_id: str | None = None,
) -> AsyncIterator[str]:
    """Yield OpenAI-compatible SSE chunks for a streamed RAG answer."""
    cancel = threading.Event()
    watcher = start_disconnect_watcher(request, cancel, label=f"Chat stream {chat_id}")
    fragments: list[str] = []
    started = request_started if request_started is not None else time.monotonic()
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
        yield format_status_chunk(
            chat_id=chat_id,
            model=model,
            created=created,
            description=RETRIEVAL_STATUS if not bypass_rag else GENERATION_STATUS,
        )

        if _timed_out():
            raise RequestTimeoutError("Request timed out before retrieval")

        remaining_timeout = None
        if deadline is not None:
            remaining_timeout = deadline - time.monotonic()
            if remaining_timeout <= 0:
                raise RequestTimeoutError("Request timed out before retrieval")

        stream_result = await run_sync_with_request_timeout(
            _fetch_stream_result,
            service,
            question,
            bypass_rag=bypass_rag,
            target_product=product,
            target_project=project,
            target_build=build,
            document_type=document_type,
            top_k=top_k,
            cancel_event=cancel,
            task=task,
            history=history,
            connectivity_query=connectivity_query,
            conversation_id=conversation_id,
            timeout_seconds=remaining_timeout,
        )
        retrieval_done_at = time.monotonic()
        first_char_at: float | None = None
        if cancel.is_set():
            logger.info("Chat stream %s cancelled before generation", chat_id)
            yield clear_status_chunk(
                chat_id=chat_id, model=model, created=created,
                description=GENERATION_STATUS,
            )
            return

        if not bypass_rag:
            yield format_status_chunk(
                chat_id=chat_id,
                model=model,
                created=created,
                description=GENERATION_STATUS,
            )

        # Compact duplicate citations (same document) and remap the LLM's dense
        # [N] markers so Open WebUI's sources stay 1:1 with the answer text and
        # clicking [N] opens the document the text actually references.
        _compacted, _marker_map = compact_citations(stream_result.citations)
        sources = citations_to_open_webui_sources(_compacted)
        if sources:
            yield _sse_chunk(
                chat_id=chat_id,
                model=model,
                created=created,
                delta={},
                sources=sources,
            )

        remaining_timeout = None
        if deadline is not None:
            remaining_timeout = deadline - time.monotonic()
            if remaining_timeout <= 0:
                raise RequestTimeoutError("Request timed out before generation")

        generation_status_active = True
        _remapper = StreamingCitationMarkerRemapper(_marker_map)
        async for fragment in iter_sync_text_chunks(
            stream_result.text_chunks,
            cancel=cancel,
            request=request,
            timeout_seconds=remaining_timeout,
        ):
            if generation_status_active:
                yield clear_status_chunk(
                    chat_id=chat_id, model=model, created=created,
                    description=GENERATION_STATUS,
                )
                generation_status_active = False
            if first_char_at is None:
                first_char_at = time.monotonic()
            remapped = _remapper.feed(fragment)
            fragments.append(remapped)
            yield _sse_chunk(
                chat_id=chat_id,
                model=model,
                created=created,
                delta={"content": remapped},
            )
        _flush = _remapper.finish()
        if _flush:
            fragments.append(_flush)
            yield _sse_chunk(
                chat_id=chat_id,
                model=model,
                created=created,
                delta={"content": _flush},
            )

        if cancel.is_set():
            logger.info("Chat stream %s cancelled (%d chars partial)", chat_id, len(fragments))
            if generation_status_active:
                yield clear_status_chunk(
                    chat_id=chat_id, model=model, created=created,
                    description=GENERATION_STATUS,
                )
            return

        if generation_status_active:
            yield clear_status_chunk(
                chat_id=chat_id, model=model, created=created,
                description=GENERATION_STATUS,
            )

        content = "".join(fragments).strip() or INSUFFICIENT_ANSWER
        insufficient = content == INSUFFICIENT_ANSWER and not stream_result.citations
        if not insufficient and stream_result.citations:
            try:
                gen_cfg = service.config.generation
                if gen_cfg.inline_citation_images:
                    image_block = build_image_block(
                        content,
                        stream_result.citations,
                        max_images=gen_cfg.max_inline_images,
                    )
                    if image_block:
                        yield _sse_chunk(
                            chat_id=chat_id,
                            model=model,
                            created=created,
                            delta={"content": image_block},
                        )
            except (AttributeError, TypeError):
                pass

        footer = _elapsed_footer(
            timing=_build_phase_timing(
                started=started,
                retrieval_done_at=retrieval_done_at,
                first_char_at=first_char_at,
            ),
            show_elapsed_time=show_elapsed_time,
            bypass_rag=bypass_rag,
        )
        if footer:
            yield _sse_chunk(
                chat_id=chat_id,
                model=model,
                created=created,
                delta={"content": footer},
            )

        phase_timing = _build_phase_timing(
            started=started,
            retrieval_done_at=retrieval_done_at,
            first_char_at=first_char_at,
        )
        logger.info(
            "Chat stream %s finished (%d chars, retrieval=%.1fs, "
            "generation=%.1fs, first_char=%.1fs)",
            chat_id,
            len(content),
            phase_timing.retrieval_seconds if phase_timing else 0.0,
            phase_timing.generation_seconds if phase_timing else 0.0,
            phase_timing.first_char_seconds if phase_timing else 0.0,
        )
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
        yield clear_status_chunk(chat_id=chat_id, model=model, created=created)
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
