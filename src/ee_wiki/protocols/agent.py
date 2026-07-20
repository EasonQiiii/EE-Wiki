"""Agent runtime protocols (ADR 0008)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Finding:
    """One specialist's evidence package for the supervisor to fuse."""

    role_id: str
    markdown: str
    insufficient: bool = False
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0


@dataclass
class SessionState:
    """Ephemeral per-turn blackboard (not a knowledge store)."""

    question: str
    product: str | None = None
    project: str | None = None
    build: str | None = None
    findings: list[Finding] = field(default_factory=list)
    tool_calls: int = 0
    steps: int = 0
    insufficient: bool = False
    direct_reply: str | None = None


@dataclass(frozen=True)
class SupervisorResult:
    """Outcome of one supervisor turn."""

    kind: str  # passthrough | hybrid | fused | insufficient (fuse-internal)
    markdown: str
    findings: tuple[Finding, ...] = ()
    roles_used: tuple[str, ...] = ()
    insufficient: bool = False
    task: str | None = None


class SpecialistRunner(Protocol):
    """Runs one config-driven specialist role."""

    def run(
        self,
        question: str,
        *,
        product: str | None,
        project: str | None,
        build: str | None,
    ) -> Finding:
        """Collect evidence for ``question`` within scope."""
        ...
