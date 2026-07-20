"""LLM extraction of fail items from Radar evidence corpus (ADR 0010)."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.classify import _generate_short_output
from ee_wiki.protocols.flames import FailItem
from ee_wiki.protocols.llm import LlmBackend

logger = get_logger(__name__)

MAX_RADAR_EXTRACT_TOKENS = 256
_FAIL_HEADER = re.compile(
    r"^FAIL_ITEMS\s*:\s*(?P<body>.*)$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_BULLET = re.compile(r"^\s*[-*]\s+(?P<msg>\S.+)$", re.MULTILINE)


def extract_fail_items_from_radar_corpus(
    corpus: str,
    *,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> list[FailItem] | None:
    """Extract fail/symptom items from a Radar text corpus via local LLM.

    Semantic extraction lives in ``prompts/fa/extract_radar_evidence.md``.
    Parsing of the model reply is structural (``FAIL_ITEMS:`` / bullets).

    Args:
        corpus: Composed title / description / diagnosis / attachments text.
        llm: Local LLM backend.
        repo_root: Repository root for the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        Fail items when the model returns a list; empty list when the model
        returns ``none``; ``None`` when the call failed or output is unusable
        (caller should fall back to asking the user).
    """
    if cancel_event and cancel_event.is_set():
        return None
    stripped = corpus.strip()
    if not stripped:
        return []

    path = repo_root / "prompts" / "fa" / "extract_radar_evidence.md"
    prompt = path.read_text(encoding="utf-8").replace("{{corpus}}", stripped).strip()

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_RADAR_EXTRACT_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("Radar evidence extraction failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not raw_output:
        return None

    return _parse_fail_items_output(raw_output)


def _parse_fail_items_output(raw_output: str) -> list[FailItem] | None:
    """Parse ``FAIL_ITEMS:`` LLM output into fail items."""
    match = _FAIL_HEADER.search(raw_output.strip())
    if match is None:
        # Tolerate a bare bullet list with no header.
        body = raw_output.strip()
    else:
        body = match.group("body").strip()

    lower = body.lower()
    if lower in {"none", "null", "n/a", "-", "无", "没有"}:
        return []
    if lower.startswith("none"):
        return []

    items: list[FailItem] = []
    for bullet in _BULLET.finditer(body):
        msg = bullet.group("msg").strip()
        if msg and msg.lower() not in {"none", "n/a"}:
            items.append(FailItem(message=msg, station="radar"))
    if items:
        return items

    # Single-line body without bullets.
    if body and "\n" not in body and lower not in {"none", "null"}:
        return [FailItem(message=body, station="radar")]

    logger.warning("Radar FAIL_ITEMS output unusable: %r", raw_output[:200])
    return None
