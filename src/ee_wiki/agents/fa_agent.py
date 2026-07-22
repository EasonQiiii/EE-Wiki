"""FaAgent: a single FA agent over the shared ToolBus (fa-session.md).

The Chat Runtime routes an ``"fa"`` mode turn here instead of the Wiki
Supervisor. FaAgent:

* ensures a :class:`FaSession` (bound ticket **or** unbound symptom),
* selects 0..N tools from its allowlist (LLM-assisted, with a deterministic
  default for unbound investigation),
* executes them through the shared :class:`ee_wiki.tools.bus.ToolBus`,
* grounds an EvidenceBundle, and
* says only from that evidence (no invented true-fail; bind hint when unbound).

Bound sessions reuse the existing, tested ``try_fa_chat_reply`` path so Radar
check-in / session-turn / diagnosis behavior is unchanged.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ee_wiki.agents.fa_session import FaSession, ensure_fa_session, unbound_header_markdown
from ee_wiki.common.config import AppConfig
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.fa_chat import try_fa_chat_reply
from ee_wiki.integrations.fa_errors import format_fa_error
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn
from ee_wiki.tools.bus import ToolBus, open_tool_bus
from ee_wiki.tools.context import ToolContext

logger = get_logger(__name__)

# Tools whose value depends on a known product/project/build.
_SCOPE_REQUIRED_TOOLS = frozenset(
    {"trace_net", "connector_pins", "module_nets", "query_schematic"}
)

# Deterministic unbound skill set (always a subset of the allowlist).
_DEFAULT_UNBOUND_SKILLS = (
    "query_schematic",
    "search_component",
    "search_debug_case",
    "engineering_search",
)

_SKILLS_LINE = re.compile(r"^SKILLS:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


@dataclass
class FaAgentResult:
    """Outcome of one FaAgent turn."""

    markdown: str
    citations: list[Any] = field(default_factory=list)
    routed_skills: tuple[str, ...] = ()
    branch: str = "fa_agent"


def _load_fa_allowlist(config: AppConfig) -> tuple[str, ...]:
    """Load the FaAgent tool allowlist from ``config/agents/fa_agent.yaml``."""
    path = config.repo_root / "config" / "agents" / "fa_agent.yaml"
    if not path.is_file():
        return tuple(_DEFAULT_UNBOUND_SKILLS)
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — fall back to a safe default
        logger.warning("Failed to load fa_agent.yaml; using default allowlist")
        return tuple(_DEFAULT_UNBOUND_SKILLS)
    tools = data.get("tools") or list(_DEFAULT_UNBOUND_SKILLS)
    return tuple(str(t) for t in tools)


def _select_skills(
    question: str,
    session: FaSession,
    *,
    allowlist: tuple[str, ...],
    llm: LlmBackend | None,
    repo_root: Path,
    cancel_event: threading.Event | None,
) -> tuple[str, ...]:
    """Pick 0..N ToolBus tools for this FA turn (allowlist-validated)."""
    if llm is not None:
        from ee_wiki.generation.classify import select_fa_skills

        skills = select_fa_skills(
            question,
            product=session.product,
            project=session.project,
            build=session.build,
            allowlist=frozenset(allowlist),
            llm=llm,
            repo_root=repo_root,
            cancel_event=cancel_event,
        )
        if skills:
            return tuple(dict.fromkeys(s for s in skills if s in allowlist))

    chosen = [s for s in _DEFAULT_UNBOUND_SKILLS if s in allowlist]
    lowered = question.lower()
    if any(k in lowered for k in ("net", "pin", "连", "trace", "脚", "位号", "net name")):
        for tool in ("trace_net", "connector_pins"):
            if tool in allowlist:
                chosen.append(tool)
    return tuple(dict.fromkeys(chosen))


def _build_tool_args(
    name: str, question: str, session: FaSession
) -> dict[str, Any]:
    """Build ToolBus args for a skill (extra keys are ignored by adapters)."""
    return {
        "query": question,
        "net": question,
        "refdes": question,
        "product": session.product,
        "project": session.project,
        "build": session.build,
    }


def _format_tool_evidence(tool_results: list[tuple[str, str]]) -> str:
    """Render tool results as a compact markdown block for the LLM summary."""
    if not tool_results:
        return "(no tool evidence)"
    lines: list[str] = []
    for name, text in tool_results:
        body = text.strip() or "(empty)"
        lines.append(f"[{name}] {body[:2000]}")
    return "\n".join(lines)


def _try_llm_summary(
    session: FaSession,
    tool_results: list[tuple[str, str]],
    *,
    llm: LlmBackend | None,
    repo_root: Path,
    cancel_event: threading.Event | None,
) -> str | None:
    """Generate a short grounded summary from tool evidence (no true-fail).

    Args:
        session: Current FA session (unbound).
        tool_results: Raw tool outputs.
        llm: Optional LLM backend.
        repo_root: Repository root for the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        Summary markdown, or ``None`` when LLM is unavailable or fails so
        the caller falls back to the raw evidence template.
    """
    if llm is None:
        return None
    path = repo_root / "prompts" / "fa" / "unbound_summary.md"
    if not path.is_file():
        return None
    template = path.read_text(encoding="utf-8")
    evidence = _format_tool_evidence(tool_results)
    prompt = (
        template.replace("{{symptom}}", session.symptom or "(unspecified)")
        .replace("{{evidence}}", evidence)
        .strip()
    )
    try:
        if callable(getattr(llm, "generate_stream", None)):
            parts: list[str] = []
            for fragment in llm.generate_stream(
                prompt, max_new_tokens=256, cancel_event=cancel_event
            ):
                if cancel_event and cancel_event.is_set():
                    return None
                parts.append(fragment)
            text = "".join(parts).strip()
        else:
            text = llm.generate(prompt, max_new_tokens=256).strip()
    except Exception:  # noqa: BLE001 — summary is best-effort
        logger.warning("FA unbound LLM summary failed", exc_info=True)
        return None
    if not text:
        return None
    return text


def _ground_and_say(
    session: FaSession,
    skills: tuple[str, ...],
    tool_results: list[tuple[str, str]],
    *,
    llm_summary: str | None = None,
) -> str:
    """Compose the grounded unbound FA reply (prose summary, no raw evidence dump).

    Tool evidence is used only to ground the LLM summary; it is never pasted
    raw into the answer. Scope travels in the invisible ``<!-- ee-wiki-scope: -->``
    marker, so the visible reply stays a short, readable prose answer.
    """
    parts: list[str] = [unbound_header_markdown(session)]

    if llm_summary:
        parts.append(llm_summary.strip())
    elif tool_results:
        # No LLM summary available: give a brief grounded note instead of the
        # raw tool JSON.
        names = ", ".join(name for name, _ in tool_results)
        parts.append(
            f"已检索以下工具：{names}。但证据不足以给出结论，"
            "请补充现象或贴 radar:// 票号以获取 diagnosis 步骤。"
        )
    else:
        parts.append("未检索到相关工具证据，无法给出基于证据的答复。")

    if not (session.product or session.project or session.build):
        parts.append(
            "**Scope 未确认：** `trace_net` / `connector_pins` / `query_schematic` "
            "需要 product/project/build。请在问句中给出（如 `logan p1`）或补充 "
            "scope，我再继续追网 / 查图。"
        )

    parts.append(
        "---\n"
        "以上仅依据工具返回的证据作答；未绑定 Radar 票时**不做 true-fail / 根因"
        "结论**。可贴 `radar://<id>` 绑定票号以拉取 diagnosis 步骤与附件。"
    )
    return "\n\n".join(parts).strip() + "\n"


class FaAgent:
    """Single FA agent that drives the shared ToolBus (fa-session.md)."""

    def __init__(
        self,
        config: AppConfig,
        bus: ToolBus,
        *,
        llm: LlmBackend | None = None,
        tool_context: ToolContext | None = None,
    ) -> None:
        """Initialize the agent.

        Args:
            config: Application configuration.
            bus: Shared read-only ToolBus.
            llm: Optional local LLM for mode/skill classification.
            tool_context: Optional tool context (used for scope inference).
        """
        self._config = config
        self._bus = bus
        self._llm = llm
        self._ctx = tool_context
        self._allowlist = _load_fa_allowlist(config)

    def handle(
        self,
        question: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        history: Sequence[ConversationTurn] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> FaAgentResult:
        """Run one FA turn and return the grounded reply.

        Args:
            question: Latest user utterance.
            product: Resolved product scope (from API body or inference).
            project: Resolved project scope.
            build: Resolved build scope.
            history: Prior conversation turns.
            cancel_event: Optional cancellation signal.

        Returns:
            :class:`FaAgentResult` with the reply markdown and routed skills.
        """
        session = ensure_fa_session(
            question,
            history,
            product,
            project,
            build,
            config=self._config,
            ctx=self._ctx,
        )

        # Bound path: reuse the existing, tested FA flow (check-in + session
        # turns + bind). It returns None only when not on the FA path.
        if session.bound and session.radar_id:
            from ee_wiki.integrations.radar.attachments import (
                format_attachment_content_markdown,
                format_attachment_download_markdown,
                wants_attachment_content,
                wants_attachment_download,
            )

            # Prefer reading file bytes over diagnosis paraphrase when the
            # user names a log / asks to analyze attachment content.
            if wants_attachment_content(question):
                try:
                    md = format_attachment_content_markdown(
                        self._config, session.radar_id, question
                    )
                except EEWikiError as exc:
                    logger.warning(
                        "FA attachment content failed radar=%s",
                        session.radar_id,
                        exc_info=True,
                    )
                    md = format_fa_error(
                        exc,
                        radar_id=session.radar_id,
                        context="attachment",
                    )
                return FaAgentResult(
                    markdown=md,
                    citations=[],
                    routed_skills=("radar_download_attachment",),
                    branch="respond",
                )

            if wants_attachment_download(question):
                try:
                    md = format_attachment_download_markdown(
                        self._config, session.radar_id, question
                    )
                except EEWikiError as exc:
                    logger.warning(
                        "FA attachment download failed radar=%s",
                        session.radar_id,
                        exc_info=True,
                    )
                    md = format_fa_error(
                        exc,
                        radar_id=session.radar_id,
                        context="attachment",
                    )
                return FaAgentResult(
                    markdown=md,
                    citations=[],
                    routed_skills=("radar_download_attachment",),
                    branch="respond",
                )

            try:
                reply = try_fa_chat_reply(
                    self._config,
                    question,
                    history,
                    user_product=product,
                    user_project=project,
                    user_build=build,
                    llm=self._llm,
                    cancel_event=cancel_event,
                )
            except EEWikiError as exc:
                logger.warning(
                    "FA chat reply failed radar=%s",
                    session.radar_id,
                    exc_info=True,
                )
                reply = format_fa_error(exc, radar_id=session.radar_id)
            if reply is not None:
                return FaAgentResult(
                    markdown=reply,
                    citations=[],
                    routed_skills=(),
                    branch="respond",
                )
            return FaAgentResult(
                markdown=(
                    f"## FA check-in — rdar://{session.radar_id}\n\n"
                    "(无可用证据；请补充现象或 paste 测试 log。)"
                ),
                citations=[],
                routed_skills=(),
                branch="respond",
            )

        # Unbound path: investigate by symptom via ToolBus.
        skills = _select_skills(
            question,
            session,
            allowlist=self._allowlist,
            llm=self._llm,
            repo_root=self._config.repo_root,
            cancel_event=cancel_event,
        )
        tool_results = self._exec_skills(skills, question, session, cancel_event)
        llm_summary = _try_llm_summary(
            session,
            tool_results,
            llm=self._llm,
            repo_root=self._config.repo_root,
            cancel_event=cancel_event,
        )
        markdown = _ground_and_say(
            session, skills, tool_results, llm_summary=llm_summary
        )
        return FaAgentResult(
            markdown=markdown,
            citations=[],
            routed_skills=skills,
            branch="fa_agent",
        )

    def _exec_skills(
        self,
        skills: tuple[str, ...],
        question: str,
        session: FaSession,
        cancel_event: threading.Event | None,
    ) -> list[tuple[str, str]]:
        """Execute each selected tool through the shared ToolBus."""
        has_scope = bool(session.product or session.project or session.build)
        results: list[tuple[str, str]] = []
        for name in skills:
            if name in _SCOPE_REQUIRED_TOOLS and not has_scope:
                # Defer to the clarify note in the reply; do not call blind.
                continue
            args = _build_tool_args(name, question, session)
            res = self._bus.call(name, args, caller_id="fa_agent")
            if res.ok:
                results.append((name, res.text))
            else:
                results.append((name, f"[tool {name} error] {res.error}"))
        return results


def open_fa_agent(
    config: AppConfig,
    *,
    tool_context: ToolContext,
    llm: LlmBackend | None = None,
) -> FaAgent:
    """Build a :class:`FaAgent` with a ToolBus from the given context.

    Args:
        config: Application configuration.
        tool_context: Prebuilt tool context (loads index if omitted).
        llm: Optional local LLM for mode / skill classification.

    Returns:
        Ready :class:`FaAgent`.
    """
    bus = open_tool_bus(
        tool_context,
        timeout_seconds=config.agents.tool_timeout_seconds,
        max_concurrent=config.agents.max_concurrent_tools,
        span_log=config.agents_span_log,
    )
    return FaAgent(config, bus, llm=llm, tool_context=tool_context)
