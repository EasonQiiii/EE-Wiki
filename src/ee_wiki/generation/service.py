"""Orchestrate retrieval, prompt rendering, and answer generation."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import Citation, RagAnswer
from ee_wiki.generation.citations import build_enriched_citations
from ee_wiki.generation.classify import classify_task
from ee_wiki.generation.context import format_context_blocks, resolve_history_for_prompt
from ee_wiki.generation.inline_images import build_image_block
from ee_wiki.generation.llm.factory import build_llm_backend
from ee_wiki.generation.prepare import PreparedQuery, prepare_query, should_prepare_query
from ee_wiki.generation.prompt_stats import prompt_size_fields
from ee_wiki.generation.templates.loader import (
    load_scope_rules,
    load_template,
    render_assistant_template,
    render_template,
    resolve_prompts_dir,
)
from ee_wiki.generation.translate import (
    build_translation_prompt,
    is_translation_task,
    log_translation_task,
)
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.hybrid.engine import HybridChunk, HybridRagEngine, RetrievalResult
from ee_wiki.retrieval.rewrite import ConversationTurn, rewrite_query
from ee_wiki.retrieval.scope_extract import InferredScope, extract_scope_rules
from ee_wiki.retrieval.scope_resolve import merge_inferred_scope, resolve_retrieval_targets

logger = get_logger(__name__)

INSUFFICIENT_ANSWER = "知识库中未找到相关内容，无法回答该问题。"


@dataclass(frozen=True)
class AnswerStreamResult:
    """Streamed answer text plus citation metadata for Open WebUI."""

    citations: list[Citation]
    text_chunks: Iterator[str]


@dataclass
class _RagPrepared:
    """Normal path: prompt + chunks are ready to generate from."""

    chunks: list[HybridChunk]
    prompt: str
    retrieval_query: str
    resolved_task: str | None
    prepared_task: str | None
    top_rerank_score: float | None


@dataclass
class _RagTranslation:
    """Route to the translation prompt (no retrieval)."""

    question: str
    history: list[ConversationTurn] | None
    cancel_event: threading.Event | None


@dataclass
class _RagAssistant:
    """Route to the assistant-meta prompt (weak KB evidence)."""

    question: str
    history: list[ConversationTurn] | None
    prepared_task: str | None
    retrieval_query: str


@dataclass
class _RagInsufficient:
    """No chunks retrieved; caller emits the insufficient-context message."""


@dataclass
class _RagCancelled:
    """A cancel event fired mid-pipeline; caller returns an empty result."""


_RagStep = (
    _RagPrepared
    | _RagTranslation
    | _RagAssistant
    | _RagInsufficient
    | _RagCancelled
)


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
        if backend != "openai":
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

    def _prepare_for_retrieval(
        self,
        question: str,
        history: list[ConversationTurn] | None,
        caller_task: str | None,
        *,
        caller_project: str | None = None,
        caller_build: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> PreparedQuery:
        """Prepare retrieval query, optional scope, and task before hybrid search.

        Args:
            question: Current user question.
            history: Prior conversation turns.
            caller_task: Explicit task from the API caller.
            caller_project: Explicit API project filter, if any.
            caller_build: Explicit API build filter, if any.
            cancel_event: Cancellation signal.

        Returns:
            Prepared retrieval query with optional scope and task fields.
        """
        gen = self.config.generation
        caller_has_scope = bool(caller_project or caller_build)
        scope_inference = gen.scope_inference and not caller_has_scope
        scope_mode = gen.scope_inference_mode
        catalog = self.engine.get_scope_catalog() if scope_inference else None

        if gen.query_prepare == "separate":
            retrieval_query = self._maybe_rewrite_query(
                question,
                history,
                cancel_event=cancel_event,
            )
            prepared_task: str | None = None
            if gen.task_classification and caller_task is None:
                prepared_task = classify_task(
                    question,
                    llm=self.llm,
                    repo_root=self.config.repo_root,
                    default_task=self.template_task,
                    cancel_event=cancel_event,
                )
            return PreparedQuery(retrieval_query=retrieval_query, task=prepared_task)

        if not should_prepare_query(
            question,
            history,
            query_rewrite=gen.query_rewrite,
            task_classification=gen.task_classification,
            caller_task=caller_task,
            scope_inference=scope_inference,
            scope_inference_mode=scope_mode,
            caller_has_scope=caller_has_scope,
        ):
            return PreparedQuery(retrieval_query=question, task=None)

        return prepare_query(
            question,
            history,
            llm=self.llm,
            repo_root=self.config.repo_root,
            default_task=self.template_task,
            query_rewrite=gen.query_rewrite,
            task_classification=gen.task_classification,
            scope_inference=scope_inference and scope_mode in {"llm", "merged"},
            catalog=catalog,
            caller_task=caller_task,
            cancel_event=cancel_event,
            max_history_turns=gen.query_rewrite_max_history_turns,
        )

    def _resolve_scope_for_retrieval(
        self,
        question: str,
        prepared: PreparedQuery,
        *,
        caller_project: str | None,
        caller_build: str | None,
    ) -> tuple[str, str | None, str | None, dict[tuple[str, str], int] | None]:
        """Resolve retrieval scope and the stripped query used for hybrid search."""
        if caller_project:
            return prepared.retrieval_query, caller_project, caller_build, None

        gen = self.config.generation
        if not gen.scope_inference:
            return prepared.retrieval_query, None, None, None

        catalog = self.engine.get_scope_catalog()
        rules_scope: InferredScope | None = None
        if gen.scope_inference_mode in {"rules", "merged"}:
            rules_scope = extract_scope_rules(question, catalog)

        inferred, stripped_from_rules = merge_inferred_scope(
            rules=rules_scope,
            prepared_product=prepared.product,
            prepared_revision=prepared.revision,
            prepared_layer=prepared.layer,
            catalog=catalog,
            stripped_from_rules=rules_scope.stripped_query if rules_scope else "",
        )

        retrieval_query = prepared.retrieval_query
        if inferred is None:
            return retrieval_query, None, None, None

        if (
            rules_scope is not None
            and prepared.product is None
            and prepared.revision is None
            and prepared.layer is None
            and rules_scope.stripped_query
        ):
            retrieval_query = rules_scope.stripped_query
        elif stripped_from_rules and prepared.retrieval_query == question:
            retrieval_query = stripped_from_rules

        target_project, target_build, scope_ranks = resolve_retrieval_targets(
            inferred,
            catalog,
            self.config.data_layout,
        )
        logger.info(
            "Inferred scope product=%s revision=%s layer=%s -> target=%s/%s",
            inferred.product,
            inferred.revision,
            inferred.layer,
            target_project,
            target_build,
        )
        return retrieval_query, target_project, target_build, scope_ranks or None

    def _resolve_task(
        self,
        caller_task: str | None,
        retrieval_query: str,
        prepared_task: str | None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> str | None:
        """Resolve the prompt task after retrieval.

        Args:
            caller_task: Explicit task from the API caller (takes priority).
            retrieval_query: Query used for retrieval (for separate-mode classify).
            prepared_task: Task from merged prepare step, if any.
            cancel_event: Cancellation signal.

        Returns:
            Resolved task name, or ``None`` to use the configured default.
        """
        if caller_task is not None:
            return caller_task
        if prepared_task is not None:
            return prepared_task
        if not self.config.generation.task_classification:
            return None
        if self.config.generation.query_prepare != "separate":
            return None
        return classify_task(
            retrieval_query,
            llm=self.llm,
            repo_root=self.config.repo_root,
            default_task=self.template_task,
            cancel_event=cancel_event,
        )

    def _maybe_rewrite_query(
        self,
        question: str,
        history: list[ConversationTurn] | None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Rewrite question using history if configured and applicable.

        Used only when ``generation.query_prepare`` is ``separate``.

        Args:
            question: Current user question.
            history: Prior conversation turns (may be None or empty).
            cancel_event: Cancellation signal.

        Returns:
            Rewritten query or the original question.
        """
        if not self.config.generation.query_rewrite:
            return question
        if not history:
            return question
        return rewrite_query(
            question,
            history,
            llm=self.llm,
            repo_root=self.config.repo_root,
            cancel_event=cancel_event,
            max_history_turns=self.config.generation.query_rewrite_max_history_turns,
        )

    def _should_use_assistant_fallback(
        self,
        task: str | None,
        retrieval: RetrievalResult,
    ) -> bool:
        """Decide whether to answer from the assistant role instead of the KB.

        Knowledge-base evidence always wins: the assistant fallback only fires
        when retrieval confidence is weak (no chunks, or the best rerank score
        falls below ``generation.weak_rerank_threshold``). The fallback prompt
        lets the LLM either introduce the assistant (identity/usage questions)
        or state that the knowledge base lacks relevant content — no separate
        intent classifier is involved.

        Args:
            task: Requested prompt task, if any.
            retrieval: Retrieval result for the (possibly rewritten) query.

        Returns:
            True when the question should get an assistant-fallback answer.
        """
        if not self.config.generation.assistant_fallback:
            return False
        if task is not None and task != self.template_task:
            return False
        if not retrieval.chunks:
            return True
        top = retrieval.top_rerank_score
        if top is None:
            return False
        return top < self.config.generation.weak_rerank_threshold

    def _load_assistant_role(self) -> str:
        """Load static assistant role text from ``prompts/{assistant_task}/role.md``."""
        role_path = (
            resolve_prompts_dir(self.config.repo_root)
            / self.config.generation.assistant_task
            / "role.md"
        )
        return role_path.read_text(encoding="utf-8").strip()

    def _build_assistant_prompt(
        self,
        question: str,
        history: list[ConversationTurn] | None = None,
        *,
        prepared_task: str | None = None,
        retrieval_query: str | None = None,
    ) -> str:
        """Render the assistant-meta prompt without retrieval context."""
        assistant_task = self.config.generation.assistant_task
        template = load_template(self.config.repo_root, assistant_task, self.template_name)
        return render_assistant_template(
            template,
            role=self._load_assistant_role(),
            question=question,
            history=resolve_history_for_prompt(
                question,
                history,
                prepared_task=prepared_task,
                retrieval_query=retrieval_query,
            ),
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
        if self.config.generation.inline_citation_images and not insufficient_context:
            image_block = build_image_block(
                answer_text,
                citations,
                max_images=self.config.generation.max_inline_images,
            )
            if image_block:
                answer_text = answer_text.rstrip() + image_block
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
        history: list[ConversationTurn] | None = None,
        prepared_task: str | None = None,
        retrieval_query: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RagAnswer:
        """Answer from the assistant role prompt when the KB has no evidence."""
        prompt = self._build_assistant_prompt(
            question,
            history,
            prepared_task=prepared_task,
            retrieval_query=retrieval_query,
        )
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

    def _answer_translation(
        self,
        question: str,
        *,
        history: list[ConversationTurn] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RagAnswer:
        """Translate conversation content or quoted text (中英互译)."""
        log_translation_task(question)
        prompt = build_translation_prompt(
            self.config.repo_root,
            question=question,
            history=history,
            template_name=self.template_name,
        )
        size = prompt_size_fields(prompt)
        logger.info(
            "Translation answer (prompt_chars=%d, prompt_tokens_est=%d)",
            size["prompt_chars"],
            size["prompt_tokens_est"],
        )
        answer_text = self._generate_answer_text(prompt, cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():
            return RagAnswer(answer="", citations=[], insufficient_context=False)
        if not answer_text:
            logger.warning("Translation LLM returned empty text")
            return RagAnswer(
                answer="无法完成翻译，请提供需要翻译的文本或先进行一次问答。",
                citations=[],
                insufficient_context=False,
            )
        return RagAnswer(answer=answer_text, citations=[], insufficient_context=False)

    def _should_translate(
        self,
        caller_task: str | None,
        prepared_task: str | None,
    ) -> bool:
        """Return whether to skip retrieval and run the translation prompt."""
        return is_translation_task(caller_task) or is_translation_task(prepared_task)

    def _prepare_and_retrieve(
        self,
        question: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
        task: str | None = None,
        cancel_event: threading.Event | None = None,
        history: list[ConversationTurn] | None = None,
    ) -> _RagStep:
        """Run the shared pre-generation pipeline for both entry points.

        ``answer`` and ``stream_answer`` share the identical steps up to prompt
        rendering: translation detection, query preparation, scope resolution,
        retrieval, assistant fallback, task resolution, and template rendering.
        This helper performs them once and returns a discriminated result so each
        caller can assemble its own return type (``RagAnswer`` vs
        ``AnswerStreamResult``).
        """
        if cancel_event and cancel_event.is_set():
            return _RagCancelled()

        if is_translation_task(task):
            return _RagTranslation(
                question=question, history=history, cancel_event=cancel_event
            )

        prepared = self._prepare_for_retrieval(
            question,
            history,
            task,
            caller_project=target_project,
            caller_build=target_build,
            cancel_event=cancel_event,
        )
        if cancel_event and cancel_event.is_set():
            return _RagCancelled()

        if self._should_translate(task, prepared.task):
            return _RagTranslation(
                question=question, history=history, cancel_event=cancel_event
            )

        retrieval_query, resolved_project, resolved_build, scope_ranks = (
            self._resolve_scope_for_retrieval(
                question,
                prepared,
                caller_project=target_project,
                caller_build=target_build,
            )
        )

        retrieval = self.engine.retrieve(
            retrieval_query,
            target_project=resolved_project,
            target_build=resolved_build,
            document_type=document_type,
            top_k_final=top_k_final,
            scope_ranks_override=scope_ranks,
        )
        if cancel_event and cancel_event.is_set():
            return _RagCancelled()

        if self._should_use_assistant_fallback(task, retrieval):
            return _RagAssistant(
                question=question,
                history=history,
                prepared_task=prepared.task,
                retrieval_query=retrieval_query,
            )

        chunks = retrieval.chunks
        if not chunks:
            logger.info("No chunks retrieved for question: %s", question)
            return _RagInsufficient()

        resolved_task = self._resolve_task(
            task,
            retrieval_query,
            prepared.task,
            cancel_event=cancel_event,
        )
        if cancel_event and cancel_event.is_set():
            return _RagCancelled()

        template = self._load_prompt_template(resolved_task)
        context = format_context_blocks(chunks)
        scope_rules = load_scope_rules(self.config.repo_root)
        prompt = render_template(
            template,
            context=context,
            question=question,
            scope_rules=scope_rules,
            history=resolve_history_for_prompt(
                question,
                history,
                task=resolved_task,
                prepared_task=prepared.task,
                retrieval_query=retrieval_query,
            ),
        )
        return _RagPrepared(
            chunks=chunks,
            prompt=prompt,
            retrieval_query=retrieval_query,
            resolved_task=resolved_task,
            prepared_task=prepared.task,
            top_rerank_score=retrieval.top_rerank_score,
        )

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
        history: list[ConversationTurn] | None = None,
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
            history: Prior conversation turns for query rewriting and prompt context.

        Returns:
            Answer text with citations, or an insufficient-context response.
        """
        step = self._prepare_and_retrieve(
            question,
            target_project=target_project,
            target_build=target_build,
            document_type=document_type,
            top_k_final=top_k_final,
            task=task,
            cancel_event=cancel_event,
            history=history,
        )
        if isinstance(step, _RagCancelled):
            return RagAnswer(answer="", citations=[], insufficient_context=False)
        if isinstance(step, _RagTranslation):
            return self._answer_translation(
                step.question, history=step.history, cancel_event=step.cancel_event
            )
        if isinstance(step, _RagAssistant):
            return self._answer_assistant_meta(
                step.question,
                history=step.history,
                prepared_task=step.prepared_task,
                retrieval_query=step.retrieval_query,
                cancel_event=cancel_event,
            )
        if isinstance(step, _RagInsufficient):
            return RagAnswer(
                answer=INSUFFICIENT_ANSWER, citations=[], insufficient_context=True
            )

        size = prompt_size_fields(step.prompt)
        logger.info(
            "Generating answer from %d chunk(s) "
            "(task=%s, top_rerank=%s, prompt_chars=%d, prompt_tokens_est=%d)",
            len(step.chunks),
            step.resolved_task or self.template_task,
            (
                f"{step.top_rerank_score:.3f}"
                if step.top_rerank_score is not None
                else "n/a"
            ),
            size["prompt_chars"],
            size["prompt_tokens_est"],
        )
        answer_text = self._generate_answer_text(step.prompt, cancel_event=cancel_event)
        if cancel_event and cancel_event.is_set():
            return RagAnswer(answer="", citations=[], insufficient_context=False)
        if not answer_text:
            logger.warning("LLM returned empty text; using insufficient-context fallback")
            return RagAnswer(
                answer=INSUFFICIENT_ANSWER, citations=[], insufficient_context=True
            )
        return self._finalize_answer(answer_text, step.chunks, insufficient_context=False)

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
        history: list[ConversationTurn] | None = None,
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
            history: Prior conversation turns for query rewriting and prompt context.

        Returns:
            Citation list plus text fragments from the LLM. When retrieval finds
            nothing, ``text_chunks`` yields a single insufficient-context message.
        """
        step = self._prepare_and_retrieve(
            question,
            target_project=target_project,
            target_build=target_build,
            document_type=document_type,
            top_k_final=top_k_final,
            task=task,
            cancel_event=cancel_event,
            history=history,
        )
        if isinstance(step, _RagCancelled):
            return AnswerStreamResult(citations=[], text_chunks=iter(()))
        if isinstance(step, _RagTranslation):
            prompt = build_translation_prompt(
                self.config.repo_root,
                question=step.question,
                history=step.history,
                template_name=self.template_name,
            )
            log_translation_task(step.question)

            def _explicit_translation_stream() -> Iterator[str]:
                yield from self._generate_answer_text_stream(
                    prompt, cancel_event=step.cancel_event
                )

            return AnswerStreamResult(
                citations=[], text_chunks=_explicit_translation_stream()
            )
        if isinstance(step, _RagAssistant):
            prompt = self._build_assistant_prompt(
                step.question,
                history=step.history,
                prepared_task=step.prepared_task,
                retrieval_query=step.retrieval_query,
            )

            def _assistant_stream() -> Iterator[str]:
                yield from self._generate_answer_text_stream(
                    prompt, cancel_event=cancel_event
                )

            return AnswerStreamResult(citations=[], text_chunks=_assistant_stream())
        if isinstance(step, _RagInsufficient):

            def _insufficient() -> Iterator[str]:
                yield INSUFFICIENT_ANSWER

            return AnswerStreamResult(citations=[], text_chunks=_insufficient())

        size = prompt_size_fields(step.prompt)
        logger.info(
            "Streaming answer from %d chunk(s) "
            "(task=%s, top_rerank=%s, prompt_chars=%d, prompt_tokens_est=%d)",
            len(step.chunks),
            step.resolved_task or self.template_task,
            (
                f"{step.top_rerank_score:.3f}"
                if step.top_rerank_score is not None
                else "n/a"
            ),
            size["prompt_chars"],
            size["prompt_tokens_est"],
        )

        citations = build_enriched_citations(step.chunks, self.config)

        def _text_stream() -> Iterator[str]:
            if cancel_event and cancel_event.is_set():
                return
            yield from self._generate_answer_text_stream(
                step.prompt, cancel_event=cancel_event
            )

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
