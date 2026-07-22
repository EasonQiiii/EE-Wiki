"""FA session helpers for ToolBus / radar specialist (ADR 0010)."""

from __future__ import annotations

import threading
from collections.abc import Sequence

from ee_wiki.common.config import AppConfig
from ee_wiki.integrations.fa_chat import (
    fa_session_radar_id_from_history,
    parse_fa_checkin_radar_id,
    try_fa_chat_reply,
)
from ee_wiki.integrations.factory import build_radar_backend
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.radar.evidence import compose_radar_evidence_corpus
from ee_wiki.integrations.session import start_fa_checkin
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn


def radar_get_problem_markdown(config: AppConfig, radar_id: str) -> str:
    """Fetch a Radar snapshot and format a short markdown summary.

    Args:
        config: Application configuration.
        radar_id: Radar / rdar identifier.

    Returns:
        Markdown summary for specialist evidence.
    """
    rid = normalize_radar_id(radar_id)
    problem = build_radar_backend(config).get_problem(rid)
    lines = [
        f"## Radar snapshot — rdar://{rid}",
        "",
        f"**Title:** {problem.title}",
        f"**State:** {problem.state or '—'} / {problem.substate or '—'}",
    ]
    if problem.component:
        lines.append(
            f"**Component:** {problem.component.name} | {problem.component.version}"
        )
    if problem.description:
        preview = problem.description[0].text.strip().replace("\n", " ")
        if len(preview) > 200:
            preview = preview[:197] + "..."
        lines.append(f"**Description:** {preview}")
    corpus = compose_radar_evidence_corpus(problem)
    if corpus:
        lines.extend(["", "### Corpus excerpt", corpus[:1500]])
    if problem.attachments:
        names = ", ".join(f"`{a.file_name}`" for a in problem.attachments[:8])
        lines.append(f"\n**Attachments:** {names}")
    return "\n".join(lines)


def fa_start_checkin_markdown(
    config: AppConfig,
    radar_id: str,
    *,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
    llm: LlmBackend | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    """Run FA check-in orchestration and return assistant markdown.

    Args:
        config: Application configuration.
        radar_id: Radar / rdar identifier.
        user_product: Optional scope override.
        user_project: Optional scope override.
        user_build: Optional scope override.
        llm: Optional LLM for Radar corpus fail extraction.
        cancel_event: Optional cancellation for LLM calls.

    Returns:
        Check-in summary markdown.
    """
    result = start_fa_checkin(
        config,
        radar_id,
        user_product=user_product,
        user_project=user_project,
        user_build=user_build,
        llm=llm,
        cancel_event=cancel_event,
    )
    return result.summary_markdown


def fa_handle_turn(
    config: AppConfig,
    question: str,
    history: Sequence[ConversationTurn] | None,
    *,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
    llm: LlmBackend | None = None,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Handle one FA/Radar turn (check-in, session lock, evidence).

    Wraps :func:`try_fa_chat_reply` for the radar specialist ToolBus path.

    Returns:
        Markdown when this turn is handled on the FA path; ``None`` when the
        caller should continue normal supervisor routing.
    """
    if not config.fa.enabled:
        return None
    checkin_id = parse_fa_checkin_radar_id(question)
    session_id = fa_session_radar_id_from_history(history)
    if not checkin_id and not session_id:
        return None
    return try_fa_chat_reply(
            config,
            question,
            history,
            user_product=user_product,
            user_project=user_project,
            user_build=user_build,
            llm=llm,
            cancel_event=cancel_event,
    )
