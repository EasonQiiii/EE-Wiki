"""Orchestrate retrieval, prompt rendering, and answer generation."""

from __future__ import annotations

from dataclasses import dataclass

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import RagAnswer
from ee_wiki.generation.context import chunks_to_citations, format_context_blocks
from ee_wiki.generation.llm.factory import build_llm_backend
from ee_wiki.generation.templates.loader import load_template, render_template
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.hybrid.engine import HybridRagEngine

logger = get_logger(__name__)

INSUFFICIENT_ANSWER = "知识库中未找到相关内容，无法回答该问题。"


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
        )

    def answer(
        self,
        question: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
    ) -> RagAnswer:
        """Retrieve context and generate a grounded answer.

        Args:
            question: User question.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            document_type: Optional document type filter.
            top_k_final: Optional retrieval result count override.

        Returns:
            Answer text with citations, or an insufficient-context response.
        """
        chunks = self.engine.retrieve(
            question,
            target_project=target_project,
            target_build=target_build,
            document_type=document_type,
            top_k_final=top_k_final,
        )
        if not chunks:
            logger.info("No chunks retrieved for question: %s", question)
            return RagAnswer(answer=INSUFFICIENT_ANSWER, citations=[], insufficient_context=True)

        template = load_template(self.config.repo_root, self.template_task, self.template_name)
        context = format_context_blocks(chunks)
        prompt = render_template(template, context=context, question=question)
        logger.info("Generating answer from %d chunk(s)", len(chunks))
        answer_text = self.llm.generate(prompt).strip()
        if not answer_text:
            logger.warning("LLM returned empty text; using insufficient-context fallback")
            return RagAnswer(answer=INSUFFICIENT_ANSWER, citations=[], insufficient_context=True)
        return RagAnswer(
            answer=answer_text,
            citations=chunks_to_citations(chunks),
            insufficient_context=False,
        )

    def answer_stream(
        self,
        question: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_final: int | None = None,
    ):
        """Retrieve context and stream a grounded answer.

        Yields:
            Text fragments from the LLM, or a single insufficient-context message.
        """
        chunks = self.engine.retrieve(
            question,
            target_project=target_project,
            target_build=target_build,
            document_type=document_type,
            top_k_final=top_k_final,
        )
        if not chunks:
            logger.info("No chunks retrieved for question: %s", question)
            yield INSUFFICIENT_ANSWER
            return

        template = load_template(self.config.repo_root, self.template_task, self.template_name)
        context = format_context_blocks(chunks)
        prompt = render_template(template, context=context, question=question)
        logger.info("Streaming answer from %d chunk(s)", len(chunks))

        emitted = False
        if hasattr(self.llm, "generate_stream"):
            for fragment in self.llm.generate_stream(prompt):
                emitted = True
                yield fragment
        else:
            text = self.llm.generate(prompt).strip()
            if text:
                emitted = True
                yield text

        if not emitted:
            logger.warning("LLM stream returned no text; using insufficient-context fallback")
            yield INSUFFICIENT_ANSWER
