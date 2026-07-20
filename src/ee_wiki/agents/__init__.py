"""Multi-agent orchestration (ADR 0008): Supervisor + config-driven specialists."""

from __future__ import annotations

from ee_wiki.agents.supervisor import Supervisor, open_supervisor

__all__ = ["Supervisor", "open_supervisor"]
