"""FaAgent: a single FA agent over the shared ToolBus (fa-session.md).

The Chat Runtime routes an ``"fa"`` mode turn here instead of the Wiki
Supervisor. FaAgent:

* ensures a :class:`FaSession` (bound ticket **or** unbound symptom),
* selects 0..N tools from its allowlist (LLM-assisted, with a deterministic
  default for unbound investigation),
* executes them through the shared :class:`ee_wiki.tools.bus.ToolBus`,
* grounds an EvidenceBundle, and
* says only from that evidence (no invented true-fail; bind hint when unbound).

Bound sessions reuse the existing, tested ``try_fa_chat_reply`` path for
check-in / session-turn / diagnosis (list & summarize steps, attachments),
but also run the shared ToolBus for **suggestion / next-action** intents
(search similar cases, engineering search, schematic module) — matching the
fa-session.md target of ``Act → Exec → Ground → Say`` for all FaMode turns.
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
from ee_wiki.integrations.fa_chat import (
    _ABOUT_DIAGNOSIS_STEPS,
    _ABOUT_FA_KEYNOTE,
    parse_fa_checkin_radar_id,
    try_fa_chat_reply,
)
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

# Tools that count as "investigation" for a bound suggestion / next-action turn.
# Deliberately excludes fa_session_turn / radar_get_problem / radar_download_attachment
# / fa_start_checkin — those are not investigation triggers (Problem 3 plan; ADR 0013
# says do NOT add a semantic regex gate; the LLM select_fa_skills decides).
_INVESTIGATION_TOOLS = frozenset(
    {
        "search_debug_case",
        "engineering_search",
        "query_schematic",
        "search_component",
        "search_datasheet",
        "trace_net",
        "connector_pins",
        "module_nets",
    }
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
    fallback_default: bool = True,
) -> tuple[str, ...]:
    """Pick 0..N ToolBus tools for this FA turn (allowlist-validated).

    Args:
        fallback_default: When True (unbound), empty / failed LLM selection
            falls back to ``_DEFAULT_UNBOUND_SKILLS``. When False (bound
            suggestion gate), empty / failed selection returns ``()`` so the
            caller can keep the read-only check-in path — never steal
            ``rdar://`` check-in with a default investigation set.
    """
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
        if skills is not None:
            # Explicit empty SKILLS: from LLM — honor it.
            return ()
        if not fallback_default:
            return ()

    if not fallback_default:
        return ()

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


def _format_keynote_reply(
    url: str,
    *,
    preview_markdown: str,
    notes: str = "",
    md_url: str | None = None,
) -> str:
    """Fixed reply for a generated FA one-page Keynote (Radar-sourced).

    Includes a short content preview so the engineer sees Summary / Steps /
    Conclusion without opening the file.
    """
    lines = [
        "## FA One-Page 已生成",
        "",
        f"[下载 FA_summary.key]({url})",
    ]
    if md_url:
        lines.append(f"[下载 FA_summary.md]({md_url})")
    lines.extend(["", preview_markdown.strip()])
    if notes.strip():
        lines.extend(["", f"_{notes.strip()}_"])
    return "\n".join(lines).rstrip() + "\n"


def _keynote_steps(problem) -> tuple[str, ...]:
    """Plain-text FA step lines from Radar diagnosis (source of truth)."""
    from ee_wiki.integrations.radar.evidence import user_diagnosis_entries

    items = user_diagnosis_entries(problem)
    if not items:
        return ()
    # Plain bodies only — formatters add the "1. 2. 3." prefix.
    return tuple(item.text.strip() for item in items if item.text.strip())


def _keynote_conclusion(problem, fail_items: tuple[str, ...]) -> str:
    """Conclusion = ticket state + latest diagnosis (no invented root cause)."""
    from ee_wiki.integrations.radar.evidence import user_diagnosis_entries
    from ee_wiki.integrations.report.keynote import build_conclusion_from_radar

    entries = user_diagnosis_entries(problem)
    latest = entries[-1].text if entries else None
    return build_conclusion_from_radar(
        state=problem.state,
        substate=problem.substate,
        latest_diagnosis=latest,
        fail_items=fail_items,
    )


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


def _fa_checkin_markdown_from_history(
    history: Sequence[ConversationTurn] | None, radar_id: str
) -> str:
    """Return the bound FA check-in assistant markdown from history (if any)."""
    if not history:
        return ""
    marker = f"## FA check-in — rdar://{radar_id}"
    for turn in reversed(history):
        if turn.role == "assistant" and marker in (turn.content or ""):
            return turn.content
    return ""


def _scope_skip_note(investigation: tuple[str, ...], session: FaSession) -> str:
    """Note which scope-required tools were skipped because scope is missing."""
    has_scope = bool(session.product or session.project or session.build)
    if has_scope:
        return ""
    skipped = sorted(s for s in investigation if s in _SCOPE_REQUIRED_TOOLS)
    if not skipped:
        return ""
    names = ", ".join(skipped)
    return (
        f"（注：以下工具因 scope 不足（缺 product/project/build）未执行：{names}。"
        "如需追网 / 查图请先补 scope。）"
    )


def _bound_suggestion_summary(
    question: str,
    radar_id: str,
    checkin: str,
    evidence: str,
    scope_note: str,
    *,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None,
) -> str | None:
    """Compose a bound-session suggestion reply from ToolBus evidence + check-in."""
    path = repo_root / "prompts" / "fa" / "bound_suggestion_summary.md"
    if not path.is_file():
        return None
    prompt = (
        path.read_text(encoding="utf-8")
        .replace("{{radar_id}}", radar_id)
        .replace("{{checkin}}", checkin.strip() or "(no check-in context)")
        .replace("{{evidence}}", evidence.strip() or "(no tool evidence)")
        .replace("{{scope_note}}", scope_note.strip())
        .replace("{{question}}", question)
        .strip()
    )
    try:
        if callable(getattr(llm, "generate_stream", None)):
            parts: list[str] = []
            for fragment in llm.generate_stream(
                prompt, max_new_tokens=512, cancel_event=cancel_event
            ):
                if cancel_event and cancel_event.is_set():
                    return None
                parts.append(fragment)
            text = "".join(parts).strip()
        else:
            text = llm.generate(prompt, max_new_tokens=512).strip()
    except Exception:  # noqa: BLE001 — summary is best-effort
        logger.warning("FA bound suggestion summary failed", exc_info=True)
        return None
    if not text:
        return None
    return text


def _ground_and_say_bound(
    session: FaSession,
    skills: tuple[str, ...],
    tool_results: list[tuple[str, str]],
    *,
    llm_summary: str | None,
) -> str:
    """Compose the grounded BOUND FA suggestion reply (no unbound header).

    The header is the bound ``## FA check-in — rdar://…``; the body distinguishes
    Radar-existing steps (recap) from EE-Wiki extra suggestions (must be grounded
    in tool evidence, marked 「非 Radar 原文」). True-fail / root-cause fabrication
    is forbidden by the prompt, not by this function.
    """
    parts: list[str] = [f"## FA check-in — rdar://{session.radar_id}", ""]
    if llm_summary:
        parts.append(llm_summary.strip())
    else:
        names = ", ".join(name for name, _ in tool_results) or "（无）"
        parts.append(
            f"已检索工具：{names}。但证据不足以给出检索型建议；"
            "票上 diagnosis 未写额外步骤，EE-Wiki 检索未执行或 scope 不足，无法给检索型建议。"
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

    def _handle_keynote_export(
        self,
        question: str,
        session: FaSession,
        product: str | None,
        project: str | None,
        build: str | None,
        cancel_event: threading.Event | None,
    ) -> FaAgentResult:
        """Generate the FA one-page Keynote for a bound ticket.

        All slide content comes from Radar (summary table, diagnosis steps,
        conclusion = state + latest diagnosis). Uses AppleScript Keynote on
        macOS when available; otherwise writes the same one-pager as text.
        """
        from urllib.parse import quote

        from ee_wiki.integrations.report.keynote import format_one_pager_markdown
        from ee_wiki.integrations.session import (
            generate_fa_summary,
            public_url,
            start_fa_checkin,
        )
        from ee_wiki.protocols.fa_report import FaReportRequest

        rid = session.radar_id
        checkin = start_fa_checkin(
            self._config,
            rid,
            user_product=product,
            user_project=project,
            user_build=build,
            llm=self._llm,
            cancel_event=cancel_event,
        )
        scope = checkin.scope
        problem = checkin.problem
        fail_items = tuple(
            f"[{item.station or '?'}] {item.message}"
            for item in checkin.fail_items.fail_items
        )
        steps = _keynote_steps(problem)
        conclusion = _keynote_conclusion(problem, fail_items)
        report_req = FaReportRequest(
            radar_id=rid,
            product=scope.product or product,
            project=scope.project or project,
            build=scope.build or build,
            title=problem.title,
            state=problem.state,
            substate=problem.substate,
            fail_items=fail_items,
            steps=steps,
            conclusion=conclusion,
        )
        report, url = generate_fa_summary(
            self._config,
            rid,
            product=report_req.product,
            project=report_req.project,
            build=report_req.build,
            fail_items=fail_items,
            steps=steps,
            title=problem.title,
            state=problem.state,
            substate=problem.substate,
            conclusion=conclusion,
        )
        preview = format_one_pager_markdown(report_req)
        md_rel = f"fa/{rid}/FA_summary.md"
        md_url = public_url(self._config, f"/v1/exports/{quote(md_rel, safe='/')}")
        return FaAgentResult(
            markdown=_format_keynote_reply(
                url,
                preview_markdown=preview,
                notes=report.notes,
                md_url=md_url,
            ),
            citations=[],
            routed_skills=("fa_export_keynote",),
            branch="fa_report",
        )

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

        # Step 0: FA one-page Keynote export (structural fast-path, ADR 0013:
        # regex token, not semantic). Bound sessions generate the .key from
        # Radar summary / diagnosis / conclusion; unbound ask to bind first.
        if _ABOUT_FA_KEYNOTE.search(question):
            if session.bound and session.radar_id:
                return self._handle_keynote_export(
                    question, session, product, project, build, cancel_event
                )
            return FaAgentResult(
                markdown=(
                    "请先发 `rdar://<id>` 绑定票号，我再整理成 FA one-page keynote。"
                ),
                citations=[],
                routed_skills=("fa_export_keynote",),
                branch="fa_report",
            )

        # Bound path. Check-in / session-turn / diagnosis (list & summarize
        # steps, attachments) reuse the tested try_fa_chat_reply path; a
        # suggestion / next-action intent additionally runs the shared ToolBus
        # (fa-session.md: Act -> Exec -> Ground -> Say for all FaMode turns).
        if session.bound and session.radar_id:
            from ee_wiki.integrations.factory import build_radar_backend
            from ee_wiki.integrations.radar.attachments import (
                format_attachment_content_markdown,
                format_attachment_download_markdown,
                format_attachment_inventory_markdown,
                resolve_requested_attachments,
                wants_attachment_content,
                wants_attachment_download,
                wants_attachment_inventory,
            )

            # Step 0.5: attachment inventory (structural fast-path, ADR 0013:
            # regex token, not semantic). "有哪些附件" / "调用 radar 工具" must
            # NOT reach the LLM — the deterministic formatter enumerates every
            # attachment (incl. .log/.zip/pictures) from problem.attachments and
            # never claims "no log". If a specific file name is named, route to
            # the on-demand download formatter instead.
            if wants_attachment_inventory(question):
                try:
                    problem = build_radar_backend(self._config).get_problem(
                        session.radar_id
                    )
                    named = resolve_requested_attachments(
                        question, list(problem.attachments)
                    )
                    if named:
                        md = format_attachment_download_markdown(
                            self._config, session.radar_id, question
                        )
                    else:
                        md = format_attachment_inventory_markdown(
                            self._config, session.radar_id
                        )
                except EEWikiError as exc:
                    logger.warning(
                        "FA attachment inventory failed radar=%s",
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
                    routed_skills=("radar_list_attachments",),
                    branch="respond",
                )

            # Step 1: attachment structural paths (unchanged).
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

            # Step 1.5: structural Radar check-in (rdar:// / radar://). Must run
            # before skill selection — otherwise an empty/failed select_fa_skills
            # must not fall through to investigation tools and skip start_fa_checkin.
            if parse_fa_checkin_radar_id(question):
                return self._bound_readonly_reply(
                    question, history, product, project, build,
                    cancel_event, session.radar_id,
                )

            # Step 2: diagnosis-steps structural pre-filter (Problem 2). A
            # list/summarize-steps question goes straight to the read-only
            # session reply — no ToolBus, no extra LLM skill selection.
            if _ABOUT_DIAGNOSIS_STEPS.search(question):
                return self._bound_readonly_reply(
                    question, history, product, project, build,
                    cancel_event, session.radar_id,
                )

            # Step 3: LLM skill selection (same allowlist machinery as unbound).
            # If the model picks investigation tools, run the ToolBus chain with
            # a bound grounding prompt; otherwise fall back to the read-only reply.
            # Bound must NOT use the unbound default skill set (fallback_default=
            # False): empty / failed selection means stay read-only.
            if self._llm is not None:
                skills = _select_skills(
                    question,
                    session,
                    allowlist=self._allowlist,
                    llm=self._llm,
                    repo_root=self._config.repo_root,
                    cancel_event=cancel_event,
                    fallback_default=False,
                )
                investigation = tuple(s for s in skills if s in _INVESTIGATION_TOOLS)
                if investigation:
                    tool_results = self._exec_skills(
                        investigation, question, session, cancel_event
                    )
                    llm_summary = _bound_suggestion_summary(
                        question,
                        session.radar_id,
                        _fa_checkin_markdown_from_history(history, session.radar_id),
                        _format_tool_evidence(tool_results),
                        _scope_skip_note(investigation, session),
                        llm=self._llm,
                        repo_root=self._config.repo_root,
                        cancel_event=cancel_event,
                    )
                    markdown = _ground_and_say_bound(
                        session, investigation, tool_results, llm_summary=llm_summary
                    )
                    return FaAgentResult(
                        markdown=markdown,
                        citations=[],
                        routed_skills=investigation,
                        branch="fa_agent",
                    )

            # Fallback: read-only session reply (no tools).
            return self._bound_readonly_reply(
                question, history, product, project, build,
                cancel_event, session.radar_id,
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

    def _bound_readonly_reply(
        self,
        question: str,
        history: Sequence[ConversationTurn] | None,
        product: str | None,
        project: str | None,
        build: str | None,
        cancel_event: threading.Event | None,
        radar_id: str,
    ) -> FaAgentResult:
        """Read-only bound reply via the tested ``try_fa_chat_reply`` path."""
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
                "FA chat reply failed radar=%s", radar_id, exc_info=True
            )
            reply = format_fa_error(exc, radar_id=radar_id)
        if reply is not None:
            return FaAgentResult(
                markdown=reply,
                citations=[],
                routed_skills=(),
                branch="respond",
            )
        return FaAgentResult(
            markdown=(
                f"## FA check-in — rdar://{radar_id}\n\n"
                "(无可用证据；请补充现象或 paste 测试 log。)"
            ),
            citations=[],
            routed_skills=(),
            branch="respond",
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
