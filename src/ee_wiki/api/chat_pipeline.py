"""Shared chat pipeline helpers (ADR 0012).

Supervisor-first routing: chat calls Supervisor for every knowledge turn when
``agents.enabled`` is true. FA / connectivity authority lives in ToolBus tools
invoked by specialists (``radar``, ``hw``, ``pcb``), not in pre-RAG hard gates.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


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
    mode: str = "none"
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
            "roles=%s llm_calls=%d scope_source=%s branch=%s mode=%s "
            "evidence_only=%s phase_ms=%s",
            self.gate,
            self.route_mode,
            self.task_owner,
            self.task,
            list(self.roles),
            self.llm_calls,
            self.scope_source,
            self.branch,
            self.mode,
            self.evidence_only,
            {k: round(v, 1) for k, v in self.phase_ms.items()},
        )


def scope_source_label(
    *,
    product: str | None,
    project: str | None,
    build: str | None,
    carried: bool = False,
) -> str:
    """Return a coarse scope provenance label for RequestTrace.

    ``carried`` marks scope recovered from the prior turn in the same
    conversation (api.carry_scope_across_turns), distinguishing it from scope
    supplied explicitly via the request body.
    """
    if product or project or build:
        return "carry" if carried else "api"
    return "none"
