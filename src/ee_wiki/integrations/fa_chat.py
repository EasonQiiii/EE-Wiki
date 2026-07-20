"""Open WebUI FA entry: Radar check-in and manual evidence paste (ADR 0010).

Lightweight intent routing — not the V4 agent supervisor. Full ``agents/``
FA orchestration still waits on ADR 0008 §8.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.integrations.flames.parse import extract_errors_from_text
from ee_wiki.integrations.paths import normalize_radar_id
from ee_wiki.integrations.session import ingest_fa_user_evidence, start_fa_checkin
from ee_wiki.retrieval.rewrite import ConversationTurn

logger = get_logger(__name__)

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
_AWAITING_RADAR = re.compile(
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


def awaiting_radar_id_from_history(
    history: Sequence[ConversationTurn] | None,
) -> str | None:
    """Return Radar id when the last FA assistant turn asked for test evidence.

    Args:
        history: Prior turns (excluding the current user message).

    Returns:
        Radar id awaiting paste, or ``None``.
    """
    if not history:
        return None
    for turn in reversed(history):
        if turn.role != "assistant":
            continue
        match = _AWAITING_RADAR.search(turn.content)
        if not match:
            return None
        awaiting = (
            "Need test evidence" in turn.content
            or "Flames API is not available" in turn.content
            or "please paste" in turn.content.lower()
        )
        return match.group("id") if awaiting else None
    return None


def looks_like_fa_evidence(text: str) -> bool:
    """Return whether ``text`` looks like a pasted log or fail list."""
    return _looks_like_evidence_body(text.strip())


def try_fa_chat_reply(
    config: AppConfig,
    question: str,
    history: Sequence[ConversationTurn] | None = None,
    *,
    user_product: str | None = None,
    user_project: str | None = None,
    user_build: str | None = None,
) -> str | None:
    """Handle FA check-in / evidence paste; otherwise return ``None`` for RAG.

    Args:
        config: Application configuration (``fa.enabled`` gates this path).
        question: Current user message.
        history: Prior conversation turns.
        user_product: Optional explicit API product filter.
        user_project: Optional explicit API project filter.
        user_build: Optional explicit API build filter.

    Returns:
        Markdown reply for Open WebUI, or ``None`` to continue normal RAG.
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
        )
        logger.info(
            "FA chat check-in radar=%s awaiting=%s",
            checkin_id,
            result.awaiting_user_evidence,
        )
        return result.summary_markdown

    awaiting_id = awaiting_radar_id_from_history(history)
    if awaiting_id and looks_like_fa_evidence(question):
        station = _parse_station(question)
        body = _strip_station_line(question)
        result = ingest_fa_user_evidence(
            config,
            awaiting_id,
            body,
            station=station,
            user_product=user_product,
            user_project=user_project,
            user_build=user_build,
        )
        logger.info(
            "FA chat evidence radar=%s fails=%d awaiting=%s",
            awaiting_id,
            len(result.fail_items.fail_items),
            result.awaiting_user_evidence,
        )
        return result.summary_markdown

    return None


def _looks_like_evidence_body(text: str) -> bool:
    if len(text) < 3:
        return False
    if extract_errors_from_text(text):
        return True
    upper = text.upper()
    return "ERROR" in upper or "FAIL" in upper


def _parse_station(text: str) -> str | None:
    match = _STATION_LINE.search(text)
    if not match:
        return None
    return match.group("station").strip()


def _strip_station_line(text: str) -> str:
    return _STATION_LINE.sub("", text).strip()
