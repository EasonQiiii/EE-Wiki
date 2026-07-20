"""Open WebUI FA entry: Radar check-in and session-locked turns (ADR 0010).

Lightweight intent routing — not the V4 agent supervisor. Full ``agents/``
FA orchestration still waits on ADR 0008 §8.

Semantic judgments (evidence vs stay inside an FA chat) use the local LLM and
``prompts/fa/classify_message.md``. Regex here is only for structural tokens
(Radar ids in headers / URLs), not for "does this look like a log?".
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.session import ingest_fa_user_evidence, start_fa_checkin
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.retrieval.rewrite import ConversationTurn

logger = get_logger(__name__)

# Structural entry: Radar URL / id tokens (not semantic "is this FA?" NLP).
_CHECKIN_VERB = re.compile(
    r"(?:new\s+check\s*in|check\s*in|开案|"
    r"(?:帮(?:我|忙)\s*)?(?:做(?:个|一下)?\s*)?(?:FA|分析)(?:\s*一下)?|"
    r"FA(?:\s*一下)?)\s*"
    r"(?:rdar://|radar://|radar\s+)?(?P<id>\d{5,})",
    re.IGNORECASE,
)
_CHECKIN_BARE = re.compile(
    r"^(?:rdar://|radar://|radar\s+)(?P<id>\d{5,})\s*$",
    re.IGNORECASE,
)
_CHECKIN_RADAR_ANYWHERE = re.compile(
    r"(?:rdar://|radar://|radar\s+)(?P<id>\d{5,})",
    re.IGNORECASE,
)
_CHECKIN_FA_HINT = re.compile(
    r"(?:FA|分析|开案|check\s*in|失效|帮我|帮忙)",
    re.IGNORECASE,
)
_FA_SESSION_RADAR = re.compile(
    r"FA check-in\s*[—-]\s*rdar://(?P<id>\d{5,})",
    re.IGNORECASE,
)
_STATION_LINE = re.compile(
    r"^\s*station\s*[:=]\s*(?P<station>\S.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_fa_checkin_radar_id(text: str) -> str | None:
    """Extract a Radar id from an FA check-in style user message.

    Args:
        text: Latest user utterance.

    Returns:
        Digits-only Radar id, or ``None`` when this is not a check-in intent.
    """
    stripped = text.strip()
    if not stripped:
        return None
    match = _CHECKIN_VERB.search(stripped)
    if match:
        return normalize_radar_id(match.group("id"))
    match = _CHECKIN_BARE.fullmatch(stripped)
    if match:
        return normalize_radar_id(match.group("id"))
    # radar://ID first, then “帮我分析一下” (or other FA hint) anywhere.
    if _CHECKIN_FA_HINT.search(stripped):
        match = _CHECKIN_RADAR_ANYWHERE.search(stripped)
        if match:
            return normalize_radar_id(match.group("id"))
    return None


def fa_session_radar_id_from_history(
    history: Sequence[ConversationTurn] | None,
) -> str | None:
    """Return Radar id when this chat is already an FA session.

    Looks for an assistant ``FA check-in — rdar://…`` header. Once present,
    the chat stays on the FA path (no silent RAG fallthrough).

    Args:
        history: Prior turns (excluding the current user message).

    Returns:
        Bound Radar id, or ``None`` when this is not an FA chat.
    """
    if not history:
        return None
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        match = _FA_SESSION_RADAR.search(turn.content)
        if match:
            return normalize_radar_id(match.group("id"))
        # Stop at the first assistant turn without an FA header so an older
        # FA reply in a long mixed history does not re-bind the session.
        return None
    return None


def awaiting_radar_id_from_history(
    history: Sequence[ConversationTurn] | None,
) -> str | None:
    """Return Radar id when the last FA assistant turn asked for test evidence.

    Args:
        history: Prior turns (excluding the current user message).

    Returns:
        Radar id awaiting paste, or ``None``.
    """
    session_id = fa_session_radar_id_from_history(history)
    if not session_id or not history:
        return None
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        awaiting = (
            "Need test evidence" in turn.content
            or "Flames API is not available" in turn.content
            or "please paste" in turn.content.lower()
        )
        return session_id if awaiting else None
    return None


def try_fa_chat_reply(
    config: AppConfig,
    question: str,
    history: Sequence[ConversationTurn] | None = None,
    *,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
    llm: LlmBackend | None = None,
    cancel_event: threading.Event | None = None,
) -> str | None:
    """Handle FA check-in / session turns; otherwise return ``None`` for RAG.

    When history already contains an FA check-in, the reply stays on the FA
    path. Evidence vs stay is classified by the local LLM (prompt-driven);
    without an LLM the session defaults to ``stay`` (ask again, never RAG).

    Args:
        config: Application configuration (``fa.enabled`` gates this path).
        question: Current user message.
        history: Prior conversation turns.
        user_product: Optional explicit API product filter.
        user_project: Optional explicit API project filter.
        user_build: Optional explicit API build filter.
        llm: Optional local LLM for in-session message classification.
        cancel_event: Optional cancellation for the classify call.

    Returns:
        Markdown reply for Open WebUI, or ``None`` only when this chat is not
        on the FA path yet (caller may continue normal RAG).
    """
    if not config.fa.enabled:
        return None

    checkin_id = parse_fa_checkin_radar_id(question)
    if checkin_id:
        result = start_fa_checkin(
            config,
            checkin_id,
            user_product=user_product,
            user_project=user_project,
            user_build=user_build,
            llm=llm,
            cancel_event=cancel_event,
        )
        logger.info(
            "FA chat check-in radar=%s awaiting=%s",
            checkin_id,
            result.awaiting_user_evidence,
        )
        return result.summary_markdown

    session_id = fa_session_radar_id_from_history(history)
    if not session_id:
        return None

    kind = _classify_session_message(
        config,
        question,
        radar_id=session_id,
        llm=llm,
        cancel_event=cancel_event,
    )
    if kind == "evidence":
        station = _parse_station(question)
        body = _strip_station_line(question)
        result = ingest_fa_user_evidence(
            config,
            session_id,
            body,
            station=station,
            user_product=user_product,
            user_project=user_project,
            user_build=user_build,
        )
        logger.info(
            "FA chat evidence radar=%s fails=%d awaiting=%s",
            session_id,
            len(result.fail_items.fail_items),
            result.awaiting_user_evidence,
        )
        return result.summary_markdown

    logger.info("FA chat session-locked stay radar=%s", session_id)
    return _session_stay_reply(session_id)


def _classify_session_message(
    config: AppConfig,
    question: str,
    *,
    radar_id: str,
    llm: LlmBackend | None,
    cancel_event: threading.Event | None,
) -> str:
    """Return ``evidence`` or ``stay`` for a bound FA session turn."""
    if llm is None:
        logger.info(
            "FA session classify skipped (no LLM) — default stay rdar://%s",
            radar_id,
        )
        return "stay"

    # Lazy import: integrations may call generation only when an LLM is wired.
    from ee_wiki.generation.classify import classify_fa_message

    kind = classify_fa_message(
        question,
        radar_id=radar_id,
        llm=llm,
        repo_root=config.repo_root,
        cancel_event=cancel_event,
    )
    return kind if kind == "evidence" else "stay"


def _session_stay_reply(radar_id: str) -> str:
    """Markdown when the user stays in FA but did not paste evidence."""
    rid = normalize_radar_id(radar_id)
    return (
        f"## FA check-in — rdar://{rid}\n\n"
        "This chat is locked to the FA session above. "
        "Paste the **test log** (preferred) or a bullet list of "
        "**error / fail** items to continue triage.\n\n"
        "Optional: `station: <name>` and serial (SN).\n\n"
        "For general wiki questions (part parameters, procedures, etc.), "
        "open a **new** Open WebUI chat — this thread will not fall back to RAG."
    )


def _parse_station(text: str) -> str | None:
    match = _STATION_LINE.search(text)
    if not match:
        return None
    return match.group("station").strip()


def _strip_station_line(text: str) -> str:
    return _STATION_LINE.sub("", text).strip()
