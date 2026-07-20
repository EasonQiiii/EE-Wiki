"""Generic config-driven specialist runner (ADR 0008)."""

from __future__ import annotations

import json
import re
from typing import Any

from ee_wiki.agents.roles import RolePack
from ee_wiki.common.logging import get_logger
from ee_wiki.protocols.agent import Finding
from ee_wiki.tools.bus import ToolBus
from ee_wiki.tools.scope import ScopeEnvelope

logger = get_logger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{2,}")


def extract_tokens(question: str, *, limit: int = 12) -> str:
    """Extract compact keyword tokens from a question for tool queries."""
    tokens = _TOKEN_RE.findall(question)
    # Prefer longer / uppercase-ish tokens (nets, designators)
    ranked = sorted(set(tokens), key=lambda t: (-len(t), t.lower()))
    return " ".join(ranked[:limit])


class Specialist:
    """Runs one role pack's recipe through the ToolBus."""

    def __init__(self, pack: RolePack, bus: ToolBus) -> None:
        """Bind a role pack to a ToolBus.

        Args:
            pack: Validated role configuration.
            bus: Shared ToolBus gateway.
        """
        self.pack = pack
        self._bus = bus

    def run(
        self,
        question: str,
        *,
        product: str | None,
        project: str | None,
        build: str | None,
        max_tool_calls: int | None = None,
    ) -> Finding:
        """Execute the role recipe and return a finding.

        Args:
            question: User question.
            product: Scope product.
            project: Scope project.
            build: Scope build.
            max_tool_calls: Optional override for this turn.

        Returns:
            :class:`Finding` with markdown evidence or ``insufficient``.
        """
        budget = max_tool_calls if max_tool_calls is not None else self.pack.max_tool_calls
        scope = ScopeEnvelope(product=product, project=project, build=build)
        tokens = extract_tokens(question)
        sections: list[str] = [f"### {self.pack.display_name} (`{self.pack.id}`)"]
        calls = 0
        useful = 0

        for step in self.pack.recipe:
            if calls >= budget:
                break
            if step.tool not in self.pack.tools:
                logger.warning(
                    "Skipping recipe step outside allowlist: role=%s tool=%s",
                    self.pack.id,
                    step.tool,
                )
                continue
            args = dict(step.args)
            if step.query_from == "question":
                args.setdefault("query", question)
            elif step.query_from == "tokens":
                args.setdefault("query", tokens or question)
                # Connectivity tools use different primary keys
                if step.tool == "trace_net" and "net" not in args:
                    args["net"] = tokens.split()[0] if tokens else question
                if step.tool == "connector_pins" and "refdes" not in args:
                    args["refdes"] = tokens.split()[0] if tokens else question
                if step.tool == "module_nets" and "module" not in args:
                    args["module"] = tokens.split()[0] if tokens else question

            result = self._bus.call(
                step.tool,
                args,
                caller_id=self.pack.id,
                scope=scope,
            )
            calls += 1
            if not result.ok:
                sections.append(f"- `{step.tool}` error: {result.error}")
                continue
            if self._looks_empty(result.text):
                sections.append(f"- `{step.tool}`: no useful hits")
                continue
            useful += 1
            sections.append(f"#### Tool `{step.tool}`")
            sections.append(self._preview(result.text))

        insufficient = useful == 0
        if insufficient:
            sections.append(
                "_Insufficient evidence for this role within the current scope._"
            )
        return Finding(
            role_id=self.pack.id,
            markdown="\n\n".join(sections),
            insufficient=insufficient,
            tool_calls=calls,
        )

    @staticmethod
    def _looks_empty(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        try:
            payload: Any = json.loads(stripped)
        except json.JSONDecodeError:
            return len(stripped) < 8
        if isinstance(payload, dict):
            if payload.get("error"):
                return True
            if payload.get("found") is False:
                return True
            hits = payload.get("hits") or payload.get("cases") or payload.get("pins")
            if hits is not None and len(hits) == 0:
                return True
            if payload.get("authority") == "insufficient":
                return True
        return False

    @staticmethod
    def _preview(text: str, *, max_chars: int = 2500) -> str:
        if len(text) <= max_chars:
            return f"```json\n{text}\n```"
        return f"```json\n{text[:max_chars]}\n…(truncated)\n```"
