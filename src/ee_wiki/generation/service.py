"""Orchestrate retrieval, prompt rendering, and answer generation."""

from __future__ import annotations

from dataclasses import dataclass

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import RagAnswer
from ee_wiki.generation.context import chunks_to_citations, format_context_blocks
from ee_wiki.generation.llm.local import LocalLlmBackend
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
            RuntimeError: If ``models.llm_model`` is not configured.
        """
        llm_path = config.models.llm_model
        if llm_path is None:
            raise RuntimeError("models.llm_model is not configured")
        engine = HybridRagEngine(config)
        return cls(
            config=config,
            engine=engine,
            llm=LocalLlmBackend(llm_path),
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
        answer_text = self.llm.generate(prompt)
        return RagAnswer(
            answer=answer_text,
            citations=chunks_to_citations(chunks),
            insufficient_context=False,
        )
