"""Hybrid Supervisor router (ADR 0008 / ADR 0012).

Supervisor-first routing order:

1. FA session / Radar check-in → ``radar`` role (forced)
2. Clarify when trace lacks scope or message is too vague
3. Explicit API task → role map
4. Keyword / cheap role selection (rules-first)
5. Semantic ``TASK + ROLES`` when cheap route finds no roles
6. Specialists → fuse → ``hybrid`` or ``respond`` (radar-only FA)
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

from ee_wiki.agents.clarify import needs_scope_clarify, needs_vague_clarify
from ee_wiki.agents.fuse import fuse_findings
from ee_wiki.agents.roles import RolePack, load_all_roles
from ee_wiki.agents.specialist import Specialist
from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.connectivity.query import ConnectivityQuery
from ee_wiki.generation.classify import AgentRoute, classify_agent_route
from ee_wiki.integrations.fa_chat import (
    fa_session_radar_id_from_history,
    parse_fa_checkin_radar_id,
)
from ee_wiki.protocols.agent import Finding, SessionState, SupervisorResult
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn
from ee_wiki.tools.bus import ToolBus, open_tool_bus
from ee_wiki.tools.context import ToolContext

logger = get_logger(__name__)

_FA_HEADER = "## FA check-in"


def _fa_checkin_markdown(findings: list[Finding]) -> str | None:
    """Return the first FA check-in block from radar findings (no fuse wrapper)."""
    for finding in findings:
        if finding.insufficient:
            continue
        idx = finding.markdown.find(_FA_HEADER)
        if idx >= 0:
            block = finding.markdown[idx:]
            # Drop accidental duplicate check-in blocks in the same finding.
            rest = block[len(_FA_HEADER) :]
            dup = rest.find(_FA_HEADER)
            if dup >= 0:
                block = block[: len(_FA_HEADER) + dup]
            return block.strip()
    return None


class Supervisor:
    """Owns routing, specialists, fuse intent, and clarify responses."""

    def __init__(
        self,
        config: AppConfig,
        bus: ToolBus,
        roles: dict[str, RolePack],
        *,
        connectivity_query: ConnectivityQuery | None = None,
        tool_context: ToolContext | None = None,
        llm: LlmBackend | None = None,
    ) -> None:
        """Initialize the supervisor.

        Args:
            config: Application config (budgets + FA flags).
            bus: Shared ToolBus.
            roles: Loaded role packs.
            connectivity_query: Unused; retained for call-site compatibility.
            tool_context: Optional tool context (kept for future extensions).
            llm: Optional local LLM used for semantic role routing.
        """
        self._config = config
        self._bus = bus
        self._roles = roles
        self._cq = connectivity_query
        self._tool_context = tool_context
        self._llm = llm
        self._specialists = {
            role_id: Specialist(pack, bus) for role_id, pack in roles.items()
        }
        self.last_route_mode: str = "none"
        self.last_llm_calls: int = 0

    def handle(
        self,
        question: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        history: Sequence[ConversationTurn] | None = None,
        requested_task: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> SupervisorResult:
        """Route one user question through clarify, specialists, or passthrough.

        Args:
            question: Latest user utterance.
            product: Resolved product scope (TurnScope).
            project: Resolved project scope.
            build: Resolved build scope.
            history: Prior conversation turns.
            requested_task: Explicit prompt task supplied by the API caller.
            cancel_event: Optional cancellation signal for semantic routing.

        Returns:
            :class:`SupervisorResult` with ``kind`` in
            ``clarify | respond | passthrough | hybrid``.
        """
        state = SessionState(
            question=question, product=product, project=project, build=build
        )
        agents_cfg = self._config.agents
        self.last_route_mode = "none"
        self.last_llm_calls = 0

        forced_radar = self._force_radar(question, history)
        if forced_radar:
            self.last_route_mode = "rules"
            route = AgentRoute(task="fa", roles=("radar",))
        else:
            scope_msg = needs_scope_clarify(
                question, product=product, project=project, build=build
            )
            if scope_msg:
                return SupervisorResult(
                    kind="clarify",
                    markdown=scope_msg,
                    task="wiki",
                )

            route = self._route_question(
                question,
                requested_task=requested_task,
                cancel_event=cancel_event,
            )
            if not route.roles:
                vague = needs_vague_clarify(question)
                if vague:
                    return SupervisorResult(
                        kind="clarify",
                        markdown=vague,
                        task=route.task,
                    )

        selected = list(route.roles)
        if not selected:
            logger.info(
                "Supervisor: passthrough RAG (task=%s, route_mode=%s)",
                route.task,
                self.last_route_mode,
            )
            return SupervisorResult(
                kind="passthrough",
                markdown="",
                task=route.task,
            )

        logger.info(
            "Supervisor: selected roles=%s route_mode=%s for %r",
            selected,
            self.last_route_mode,
            question[:80],
        )
        findings: list[Finding] = []
        tool_budget = agents_cfg.max_tool_calls
        history_list = list(history) if history else None

        for role_id in selected:
            if state.steps >= agents_cfg.max_steps:
                break
            if state.tool_calls >= tool_budget:
                break
            specialist = self._specialists.get(role_id)
            if specialist is None:
                continue
            remaining = tool_budget - state.tool_calls
            finding = specialist.run(
                question,
                product=product,
                project=project,
                build=build,
                max_tool_calls=min(
                    specialist.pack.max_tool_calls,
                    remaining,
                ),
                history=history_list,
            )
            findings.append(finding)
            state.findings.append(finding)
            state.tool_calls += finding.tool_calls
            state.steps += 1

        fused = fuse_findings(
            question,
            findings,
            product=product,
            project=project,
            build=build,
        )

        fa_md = _fa_checkin_markdown(findings) if selected == ["radar"] else None
        if fa_md:
            return SupervisorResult(
                kind="respond",
                markdown=fa_md,
                task=route.task,
                findings=fused.findings,
                roles_used=fused.roles_used,
            )

        evidence = "" if fused.insufficient else fused.markdown
        return SupervisorResult(
            kind="hybrid",
            markdown=evidence,
            task=route.task,
            findings=fused.findings,
            roles_used=fused.roles_used,
            insufficient=False,
        )

    def _force_radar(
        self,
        question: str,
        history: Sequence[ConversationTurn] | None,
    ) -> bool:
        """Return whether this turn must use the ``radar`` specialist."""
        if not self._config.fa.enabled:
            return False
        if parse_fa_checkin_radar_id(question):
            return True
        return fa_session_radar_id_from_history(history) is not None

    def _route_question(
        self,
        question: str,
        *,
        requested_task: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> AgentRoute:
        """Return one validated task-and-role decision (rules-first)."""
        if requested_task is not None:
            self.last_route_mode = "explicit"
            return AgentRoute(
                task=requested_task,
                roles=self._roles_for_explicit_task(requested_task),
            )

        selected = tuple(self._select_roles(question))
        if selected:
            self.last_route_mode = "rules"
            return AgentRoute(
                task=self._task_for_roles(selected),
                roles=selected,
            )

        if self._llm is not None:
            semantic = classify_agent_route(
                question,
                llm=self._llm,
                repo_root=self._config.repo_root,
                valid_roles=frozenset(self._roles),
                max_roles=self._config.agents.max_roles_per_turn,
                cancel_event=cancel_event,
            )
            self.last_llm_calls += 1
            if semantic is not None:
                self.last_route_mode = "semantic"
                return semantic

        self.last_route_mode = "none"
        return AgentRoute(task="wiki", roles=())

    def _select_roles(self, question: str) -> list[str]:
        """Return keyword-scored roles as the cheap (rules-first) router."""
        cfg = self._config.agents
        scored: list[tuple[int, str]] = []
        lower = question.lower()
        for role_id, pack in self._roles.items():
            score = 0
            for kw in pack.keywords:
                needle = kw.lower()
                if needle and needle in lower:
                    score += 1
                elif kw in question:
                    score += 1
            if score >= cfg.route_score_threshold:
                scored.append((score, role_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [role_id for _, role_id in scored[: cfg.max_roles_per_turn]]

    def _roles_for_explicit_task(self, task: str) -> tuple[str, ...]:
        """Map an explicit legacy prompt task to available specialist roles."""
        candidates = {
            "wiki": ("hw",),
            "debug": ("hw", "fa"),
            "fa": ("fa", "radar"),
            "design_review": ("pcb", "si"),
            "power": ("power",),
            "rules": ("hw",),
            "translate": (),
        }.get(task, ())
        return tuple(role for role in candidates if role in self._roles)[
            : self._config.agents.max_roles_per_turn
        ]

    @staticmethod
    def _task_for_roles(roles: tuple[str, ...]) -> str:
        """Choose a safe prompt task when keyword fallback selected roles."""
        if "radar" in roles:
            return "fa"
        if "fa" in roles:
            return "fa"
        if "power" in roles:
            return "power"
        if any(role in roles for role in ("pcb", "si", "mfg")):
            return "design_review"
        return "wiki"


def open_supervisor(
    config: AppConfig,
    *,
    tool_context: ToolContext | None = None,
    connectivity_query: ConnectivityQuery | None = None,
    llm: LlmBackend | None = None,
) -> Supervisor:
    """Build a supervisor with ToolBus and role packs from config.

    Args:
        config: Application configuration.
        tool_context: Optional prebuilt tool context (loads index if omitted).
        connectivity_query: Optional connectivity query handle.
        llm: Optional local LLM for semantic task and role routing.

    Returns:
        Ready :class:`Supervisor`.
    """
    ctx = tool_context or ToolContext.from_config(config)
    if llm is not None:
        ctx.llm = llm
    bus = open_tool_bus(
        ctx,
        timeout_seconds=config.agents.tool_timeout_seconds,
        max_concurrent=config.agents.max_concurrent_tools,
        span_log=config.agents_span_log,
    )
    roles = load_all_roles(config.agents_roles_dir)
    return Supervisor(
        config,
        bus,
        roles,
        connectivity_query=connectivity_query,
        tool_context=ctx,
        llm=llm,
    )
