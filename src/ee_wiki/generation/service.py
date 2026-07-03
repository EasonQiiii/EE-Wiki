"""Orchestrate retrieval, prompt rendering, and answer generation."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import Citation, RagAnswer
from ee_wiki.generation.citations import build_enriched_citations
from ee_wiki.generation.context import format_context_blocks
from ee_wiki.generation.intent_router import QueryRoute, classify_query_route
from ee_wiki.generation.llm.factory import build_llm_backend
from ee_wiki.generation.prompt_stats import prompt_size_fields
from ee_wiki.generation.templates.loader import (
    load_scope_rules,
    load_template,
    render_assistant_template,
    render_template,
    resolve_prompts_dir,
)
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.hybrid.engine import HybridChunk, HybridRagEngine

logger = get_logger(__name__)

INSUFFICIENT_ANSWER = "知识库中未找到相关内容，无法回答该问题。"


@dataclass(frozen=True)
class AnswerStreamResult:
    """Streamed answer text plus citation metadata for Open WebUI."""

    citations: list[Citation]
    text_chunks: Iterator[str]


@dataclass
class RagService:
    """End-to-end RAG orchestration without direct database access."""

    config: AppConfig
    engine: HybridRagEngine
    llm: LlmBackend
    template_task: str = "wiki"
    template_name: str = "default"

    @classmethod
    def from_config(cls, config: AppConfig) -> RagService:
        """Build a service from application configuration.

        Args:
            config: Loaded application configuration.

        Returns:
            Configured :class:`RagService`.

        Raises:
            RuntimeError: If the model path for ``generation.llm_backend`` is not configured.
        """
        backend = config.generation.llm_backend
        llm_path = config.models.resolve_llm_model(backend)
        if llm_path is None:
            key = config.models.llm_config_key(backend)
            raise RuntimeError(
                f"models.{key} is not configured for generation.llm_backend={backend!r}"
            )
        engine = HybridRagEngine(config)
        return cls(
            config=config,
            engine=engine,
            llm=build_llm_backend(config),
            template_task=config.generation.default_task,
            template_name=config.generation.default_template,
        )

    def _load_prompt_template(self, task: str | None = None) -> str:
        """Load the prompt template for the requested or configured task."""
        resolved_task = task or self.template_task
        return load_template(self.config.repo_root, resolved_task, self.template_name)

    def _should_route_intent(self, task: str | None) -> bool:
        """Return whether to classify assistant-meta vs engineering intent."""
        if not self.config.generation.intent_routing:
            return False
        if task is None:
            return True
        return task == self.template_task

    def _load_assistant_role(self) -> str:
        """Load static assistant role text from ``prompts/{assistant_task}/role.md``."""
        role_path = (
            resolve_prompts_dir(self.config.repo_root)
            / self.config.generation.assistant_task
            / "role.md"
        )
        return role_path.read_text(encoding="utf-8").strip()

    def _build_assistant_prompt(self, question: str) -> str:
        """Render the assistant-meta prompt without retrieval context."""
        assistant_task = self.config.generation.assistant_task
        template = load_template(self.config.repo_root, assistant_task, self.template_name)
        return render_assistant_template(
            template,
            role=self._load_assistant_role(),
            question=question,
        )

    def _finalize_answer(
        self,
        answer_text: str,
        chunks: list[HybridChunk],
        *,
        insufficient_context: bool,
    ) -> RagAnswer:
        """Attach enriched citations; keep inline ``[N]`` markers as plain text."""
        citations = build_enriched_citations(chunks, self.config)
        return RagAnswer(
            answer=answer_text,
            citations=citations,
            insufficient_context=insufficient_context,
        )

    def _generate_answer_text(
        self,
        prompt: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Generate answer text, preferring cancellable streaming when available."""
        if callable(getattr(self.llm, "generate_stream", None)):
            parts: list[str] = []
            for fragment in self.llm.generate_stream(prompt, cancel_event=cancel_event):
                if cancel_event and cancel_event.is_set():
                    break
                parts.append(fragment)
            return "".join(parts).strip()
        if cancel_event and cancel_event.is_set():
            return ""
        return self.llm.generate(prompt).strip()

    def _answer_assistant_meta(
        self,
        question: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> RagAnswer:
        """Answer identity/capability questions without retrieval."""
        prompt = self._build_assistant_prompt(question)
        size = prompt_size_fields(prompt)
        logger.info(
            "Assistant-meta answer (prompt_chars=%d, prompt_tokens_est=%d)",
            size["prompt_chars"],
            size["prompt_tokens_est"],
        )
        answer_text = self._generate_answer_text(prompt, cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():
            return RagAnswer(answer="", citations=[], insufficient_context=False)
        if not answer_text:
            logger.warning("Assistant-meta LLM returned empty text")
            return RagAnswer(answer=INSUFFICIENT_ANSWER, citations=[], insufficient_context=True)
        return RagAnswer(answer=answer_text, citations=[], insufficient_context=False)

    def answer(
        self,
        question: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
        task: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RagAnswer:
        """Retrieve context and generate a grounded answer.

        Args:
            question: User question.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            document_type: Optional document type filter.
            top_k_final: Optional retrieval result count override.
            task: Optional prompt task folder under ``prompts/`` (e.g. ``debug``).
            cancel_event: When set, stop LLM generation as soon as possible.

        Returns:
            Answer text with citations, or an insufficient-context response.
        """
        if cancel_event and cancel_event.is_set():
            return RagAnswer(answer="", citations=[], insufficient_context=False)

        if self._should_route_intent(task):
            route = classify_query_route(question, self.engine, self.config)
            if route is QueryRoute.ASSISTANT_META:
                return self._answer_assistant_meta(question, cancel_event=cancel_event)

        retrieval = self.engine.retrieve(
            question,
            target_project=target_project,
            target_build=target_build,
            document_type=document_type,
            top_k_final=top_k_final,
        )
        if cancel_event and cancel_event.is_set():
            return RagAnswer(answer="", citations=[], insufficient_context=False)

        chunks = retrieval.chunks
        if not chunks:
            logger.info("No chunks retrieved for question: %s", question)
            return RagAnswer(answer=INSUFFICIENT_ANSWER, citations=[], insufficient_context=True)

        template = self._load_prompt_template(task)
        context = format_context_blocks(chunks)
        scope_rules = load_scope_rules(self.config.repo_root)
        prompt = render_template(
            template,
            context=context,
            question=question,
            scope_rules=scope_rules,
        )
        size = prompt_size_fields(prompt)
        logger.info(
            "Generating answer from %d chunk(s) "
            "(top_rerank=%s, prompt_chars=%d, prompt_tokens_est=%d)",
            len(chunks),
            (
                f"{retrieval.top_rerank_score:.3f}"
                if retrieval.top_rerank_score is not None
                else "n/a"
            ),
            size["prompt_chars"],
            size["prompt_tokens_est"],
        )
        answer_text = self._generate_answer_text(prompt, cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():
            return RagAnswer(answer="", citations=[], insufficient_context=False)
        if not answer_text:
            logger.warning("LLM returned empty text; using insufficient-context fallback")
            return RagAnswer(answer=INSUFFICIENT_ANSWER, citations=[], insufficient_context=True)
        return self._finalize_answer(answer_text, chunks, insufficient_context=False)

    def stream_answer(
        self,
        question: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
        cancel_event: threading.Event | None = None,
        task: str | None = None,
    ) -> AnswerStreamResult:
        """Retrieve context and stream a grounded answer with citation metadata.

        Args:
            question: User question.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            document_type: Optional document type filter.
            top_k_final: Optional retrieval result count override.
            cancel_event: When set, stop LLM streaming as soon as possible.
            task: Optional prompt task folder under ``prompts/`` (e.g. ``debug``).

        Returns:
            Citation list plus text fragments from the LLM. When retrieval finds
            nothing, ``text_chunks`` yields a single insufficient-context message.
        """
        if cancel_event and cancel_event.is_set():
            return AnswerStreamResult(citations=[], text_chunks=iter(()))

        if self._should_route_intent(task):
            route = classify_query_route(question, self.engine, self.config)
            if route is QueryRoute.ASSISTANT_META:
                prompt = self._build_assistant_prompt(question)

                def _assistant_stream() -> Iterator[str]:
                    yield from self._generate_answer_text_stream(
                        prompt,
                        cancel_event=cancel_event,
                    )

                return AnswerStreamResult(citations=[], text_chunks=_assistant_stream())

        retrieval = self.engine.retrieve(
            question,
            target_project=target_project,
            target_build=target_build,
            document_type=document_type,
            top_k_final=top_k_final,
        )
        if cancel_event and cancel_event.is_set():
            return AnswerStreamResult(citations=[], text_chunks=iter(()))

        chunks = retrieval.chunks
        if not chunks:
            logger.info("No chunks retrieved for question: %s", question)

            def _insufficient() -> Iterator[str]:
                yield INSUFFICIENT_ANSWER

            return AnswerStreamResult(citations=[], text_chunks=_insufficient())

        template = self._load_prompt_template(task)
        context = format_context_blocks(chunks)
        scope_rules = load_scope_rules(self.config.repo_root)
        prompt = render_template(
            template,
            context=context,
            question=question,
            scope_rules=scope_rules,
        )
        size = prompt_size_fields(prompt)
        logger.info(
            "Streaming answer from %d chunk(s) "
            "(top_rerank=%s, prompt_chars=%d, prompt_tokens_est=%d)",
            len(chunks),
            (
                f"{retrieval.top_rerank_score:.3f}"
                if retrieval.top_rerank_score is not None
                else "n/a"
            ),
            size["prompt_chars"],
            size["prompt_tokens_est"],
        )
        citations = build_enriched_citations(chunks, self.config)

        def _text_stream() -> Iterator[str]:
            if cancel_event and cancel_event.is_set():
                return
            yield from self._generate_answer_text_stream(prompt, cancel_event=cancel_event)

        return AnswerStreamResult(citations=citations, text_chunks=_text_stream())

    def _generate_answer_text_stream(
        self,
        prompt: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> Iterator[str]:
        """Yield answer text fragments, preferring cancellable streaming."""
        if cancel_event and cancel_event.is_set():
            return
        if callable(getattr(self.llm, "generate_stream", None)):
            yield from self.llm.generate_stream(prompt, cancel_event=cancel_event)
            return
        text = self.llm.generate(prompt).strip()
        if text:
            yield text
