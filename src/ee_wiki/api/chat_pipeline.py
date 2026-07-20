"""Shared chat pipeline helpers (ADR 0012).

Owns pre-RAG hard gates and a lightweight per-turn RequestTrace so FA /
connectivity behavior stays identical for ``agents.enabled`` true and false.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.connectivity.chat import answer_trace_question
from ee_wiki.connectivity.query import ConnectivityQuery
from ee_wiki.integrations.fa_chat import try_fa_chat_reply
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn

logger = get_logger(__name__)


@dataclass(frozen=True)
class PreRagGateResult:
    """Outcome of FA / connectivity hard gates before routing or RAG."""

    kind: str  # "fa" | "connectivity"
    markdown: str
    roles_used: tuple[str, ...] = ()


@dataclass
class RequestTrace:
    """Structured span for one chat turn (ADR 0012 §8)."""

    gate: str = "none"
    route_mode: str = "none"
    task_owner: str = "legacy"
    task: str | None = None
    roles: tuple[str, ...] = ()
    llm_calls: int = 0
    scope_source: str = "none"
    branch: str = "none"
    phase_ms: dict[str, float] = field(default_factory=dict)
    evidence_only: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def mark_phase(self, name: str, started: float) -> None:
        """Record elapsed milliseconds for ``name`` since ``started`` (monotonic)."""
        self.phase_ms[name] = (time.monotonic() - started) * 1000.0

    def log(self) -> None:
        """Emit one structured info line for the completed turn."""
        logger.info(
            "RequestTrace gate=%s route_mode=%s task_owner=%s task=%s "
            "roles=%s llm_calls=%d scope_source=%s branch=%s "
            "evidence_only=%s phase_ms=%s",
            self.gate,
            self.route_mode,
            self.task_owner,
            self.task,
            list(self.roles),
            self.llm_calls,
            self.scope_source,
            self.branch,
            self.evidence_only,
            {k: round(v, 1) for k, v in self.phase_ms.items()},
        )


def pre_rag_gates(
    config: AppConfig,
    question: str,
    history: Sequence[ConversationTurn] | None,
    *,
    product: str | None,
    project: str | None,
    build: str | None,
    connectivity_query: ConnectivityQuery | None,
    llm: LlmBackend | None = None,
    cancel_event: threading.Event | None = None,
) -> PreRagGateResult | None:
    """Run FA and connectivity hard gates once for the chat turn.

    Args:
        config: Application configuration.
        question: Latest user utterance.
        history: Prior conversation turns (FA evidence follow-up).
        product: Resolved product scope.
        project: Resolved project scope.
        build: Resolved build scope.
        connectivity_query: Optional connectivity query handle.
        llm: Optional local LLM for FA in-session evidence vs stay classify.
        cancel_event: Optional cancellation for FA classify.

    Returns:
        Gate reply when FA or authoritative connectivity handles the turn;
        otherwise ``None`` so routing / RAG may proceed.
    """
    fa_reply = try_fa_chat_reply(
        config,
        question,
        history,
        user_product=product,
        user_project=project,
        user_build=build,
        llm=llm,
        cancel_event=cancel_event,
    )
    if fa_reply is not None:
        logger.info("pre_rag_gates: FA path (%d chars)", len(fa_reply))
        return PreRagGateResult(
            kind="fa",
            markdown=fa_reply,
            roles_used=("fa",),
        )

    if config.schematic_pdf.connectivity.enabled:
        trace_reply = answer_trace_question(
            question,
            cq=connectivity_query,
            connectivity_enabled=True,
            product=product,
            project=project,
            build=build,
        )
        if trace_reply is not None:
            logger.info(
                "pre_rag_gates: connectivity path (%d chars)",
                len(trace_reply),
            )
            return PreRagGateResult(
                kind="connectivity",
                markdown=trace_reply,
                roles_used=("connectivity",),
            )

    return None


def scope_source_label(
    *,
    product: str | None,
    project: str | None,
    build: str | None,
) -> str:
    """Return a coarse scope provenance label for RequestTrace."""
    if product or project or build:
        return "api"
    return "none"
