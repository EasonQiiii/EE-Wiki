"""LLM extraction of fail items from Radar evidence corpus (ADR 0010).

Two responsibilities live here, both semantic (LLM) with structural parsing:

* :func:`extract_fail_items_from_radar_corpus` — pull fail/symptom items from
  the Radar text corpus.
* :func:`extract_checkin_background` — read the Radar face (title /
  description / diagnosis / attachment names) and return a structured
  briefing, including *which* attachments the face points at as strong
  evidence (``RELATED_FILES``). Selecting related files is semantic → LLM;
  no NG/FAIL filename regex gate (ADR 0013).
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.generation.classify import _generate_short_output, _strip_reasoning
from ee_wiki.integrations.radar.evidence import compose_radar_evidence_corpus
from ee_wiki.protocols.flames import FailItem
from ee_wiki.protocols.llm import LlmBackend
from ee_wiki.protocols.radar import RadarProblem

logger = get_logger(__name__)

MAX_RADAR_EXTRACT_TOKENS = 256
MAX_CHECKIN_BACKGROUND_TOKENS = 512
_FAIL_HEADER = re.compile(
    r"^FAIL_ITEMS\s*:\s*(?P<body>.*)$",
    re.IGNORECASE | re.MULTILINE | re.DOTALL,
)
_BULLET = re.compile(r"^\s*[-*]\s+(?P<msg>\S.+)$", re.MULTILINE)
_NONE_TOKENS = {"none", "null", "n/a", "-", "无", "没有", ""}


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


@dataclass(frozen=True)
class CheckinBackground:
    """Structured read-through of a Radar face for FA check-in.

    Attributes:
        background: One or two sentences of station / DUT / context.
        true_fail_hint: Most prominent failure verbatim (empty when none).
        fa_notes: Key diagnosis points the FA engineer recorded.
        related_files: Attachment names the face points at as strong
            evidence — validated to exist in ``problem.attachments``.
        unresolved: File names referenced in the face but NOT uploaded
            (LLM-named plus any related name that failed validation).
    """

    background: str = ""
    true_fail_hint: str = ""
    fa_notes: tuple[str, ...] = field(default_factory=tuple)
    related_files: tuple[str, ...] = field(default_factory=tuple)
    unresolved: tuple[str, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        """Return whether the briefing carries no usable content."""
        return not (
            self.background
            or self.true_fail_hint
            or self.fa_notes
            or self.related_files
            or self.unresolved
        )


_BG_HEADERS = ("BACKGROUND", "TRUE_FAIL_HINT", "FA_NOTES", "RELATED_FILES",
               "UNRESOLVED")


def extract_checkin_background(
    problem: RadarProblem,
    *,
    llm: LlmBackend,
    repo_root: Path,
    cancel_event: threading.Event | None = None,
) -> CheckinBackground | None:
    """Read the Radar face via LLM and return a structured check-in briefing.

    The prompt (``prompts/fa/checkin_background.md``) instructs the model to
    pick strong-related attachments by the FA comment / full-text pointer —
    NOT by filename heuristics. We then validate ``RELATED_FILES`` against the
    actual attachment names: unknown names are demoted to ``unresolved`` so we
    never try to download a file the ticket does not carry.

    Args:
        problem: Normalized Radar snapshot.
        llm: Local LLM backend.
        repo_root: Repository root for the prompt template.
        cancel_event: Optional cancellation signal.

    Returns:
        A :class:`CheckinBackground`, or ``None`` when the LLM call failed or
        produced nothing usable (caller degrades to face-only inventory).
    """
    if cancel_event and cancel_event.is_set():
        return None
    corpus = compose_radar_evidence_corpus(problem).strip()
    if not corpus:
        return None

    path = repo_root / "prompts" / "fa" / "checkin_background.md"
    prompt = (
        path.read_text(encoding="utf-8")
        .replace("{{radar_id}}", problem.radar_id)
        .replace("{{corpus}}", corpus)
        .strip()
    )

    try:
        raw_output = _generate_short_output(
            llm,
            prompt,
            max_new_tokens=MAX_CHECKIN_BACKGROUND_TOKENS,
            cancel_event=cancel_event,
        )
    except Exception:
        logger.warning("Check-in background extraction failed", exc_info=True)
        return None

    if cancel_event and cancel_event.is_set():
        return None
    if not raw_output:
        logger.warning("Check-in background extraction returned empty output")
        return None

    logger.debug(
        "Check-in background raw LLM output (%d chars) for rdar://%s",
        len(raw_output),
        problem.radar_id,
    )

    available = {
        a.file_name.strip()
        for a in problem.attachments
        if a.file_name and a.file_name.strip()
    }
    return _parse_checkin_background(raw_output, available_names=available)


def _parse_checkin_background(
    raw_output: str,
    *,
    available_names: set[str],
) -> CheckinBackground | None:
    """Parse the structured briefing and validate ``RELATED_FILES``."""
    text = _strip_reasoning(raw_output).strip()
    if not text:
        return None
    sections = _split_bg_sections(text)
    if not sections:
        return None

    background = _scalar(sections.get("BACKGROUND", ""))
    true_fail = _scalar(sections.get("TRUE_FAIL_HINT", ""))
    fa_notes = _bullets(sections.get("FA_NOTES", ""))

    related_raw = _bullets(sections.get("RELATED_FILES", ""))
    unresolved = list(_bullets(sections.get("UNRESOLVED", "")))

    related: list[str] = []
    for name in related_raw:
        matched = _match_related_attachment_name(name, available_names)
        if matched is not None:
            if matched not in related:
                related.append(matched)
            continue
        # No attachment match — keep a cleaned token in unresolved so the
        # engineer sees what the model pointed at (not raw backticks / junk).
        cleaned = _normalize_attachment_name_token(name) or name.strip()
        if cleaned and cleaned not in unresolved and cleaned not in related:
            unresolved.append(cleaned)

    # Also normalize any UNRESOLVED entries the model emitted directly.
    unresolved = _normalize_unresolved_names(unresolved, available_names, related)

    result = CheckinBackground(
        background=background,
        true_fail_hint=true_fail,
        fa_notes=tuple(fa_notes),
        related_files=tuple(related),
        unresolved=tuple(unresolved),
    )
    if result.is_empty():
        logger.warning(
            "Check-in background output unusable: %r", raw_output[:200]
        )
        return None
    return result


def _normalize_attachment_name_token(raw: str) -> str:
    """Strip LLM wrapping junk from an attachment name candidate.

    Structural only: backticks/quotes, trailing punctuation, trailing
    parenthetical type hints (``(log)`` / ``（日志）``), and basename of a
    path-like token. Does **not** guess relevance from NG/FAIL substrings.
    """
    s = (raw or "").strip()
    if not s:
        return ""
    # Iteratively peel wrappers / trailing junk Qwen often adds.
    for _ in range(4):
        prev = s
        while len(s) >= 2 and s[0] in "`\"'" and s[-1] == s[0]:
            s = s[1:-1].strip()
        s = s.strip("`\"'")
        s = re.sub(r"\s*[\(（][^）\)]*[\)）]\s*$", "", s).strip()
        s = re.sub(r"[,;:!?？！。.…]+$", "", s).strip()
        s = s.rstrip(".").strip()
        if s == prev:
            break
    if s and ("/" in s or "\\" in s):
        s = Path(s).name
    return s.strip()


def _match_related_attachment_name(
    raw: str,
    available_names: set[str],
) -> str | None:
    """Map an LLM RELATED_FILES token onto an exact attachment file name.

    Returns the canonical name from ``available_names``, or ``None`` when no
    unique match exists (caller demotes to ``UNRESOLVED``).
    """
    if not available_names:
        return None
    cleaned = _normalize_attachment_name_token(raw)
    if not cleaned:
        return None
    if cleaned in available_names:
        return cleaned

    by_lower = {name.lower(): name for name in available_names}
    hit = by_lower.get(cleaned.lower())
    if hit is not None:
        return hit

    cleaned_base = Path(cleaned).name
    basename_hits = [
        name
        for name in available_names
        if Path(name).name.lower() == cleaned_base.lower()
    ]
    if len(basename_hits) == 1:
        return basename_hits[0]
    if len(basename_hits) > 1:
        return None

    # Unique endswith only when the candidate looks like a real file token
    # (has a dot, or is long enough) — avoid matching bare "log" to every *.log.
    if "." in cleaned_base or len(cleaned_base) >= 8:
        suffix_hits = [
            name
            for name in available_names
            if Path(name).name.lower().endswith(cleaned_base.lower())
            or cleaned_base.lower().endswith(Path(name).name.lower())
        ]
        # Prefer exact-length / contained filename over loose suffix chains.
        exactish = [
            name
            for name in suffix_hits
            if Path(name).name.lower() == cleaned_base.lower()
            or cleaned_base.lower() in Path(name).name.lower()
        ]
        pool = exactish or suffix_hits
        if len(pool) == 1:
            return pool[0]
    return None


def _normalize_unresolved_names(
    unresolved: list[str],
    available_names: set[str],
    related: list[str],
) -> list[str]:
    """Clean UNRESOLVED tokens; promote any that actually match attachments."""
    out: list[str] = []
    for raw in unresolved:
        matched = _match_related_attachment_name(raw, available_names)
        if matched is not None:
            if matched not in related:
                related.append(matched)
            continue
        cleaned = _normalize_attachment_name_token(raw) or raw.strip()
        if cleaned and cleaned not in out and cleaned not in related:
            out.append(cleaned)
    return out


def _split_bg_sections(text: str) -> dict[str, str]:
    """Split ``HEADER:`` blocks into a mapping keyed by header name."""
    positions: list[tuple[str, int, int]] = []
    for header in _BG_HEADERS:
        m = re.search(rf"^{header}\s*:", text, re.IGNORECASE | re.MULTILINE)
        if m is not None:
            positions.append((header, m.start(), m.end()))
    if not positions:
        return {}
    positions.sort(key=lambda item: item[1])
    sections: dict[str, str] = {}
    for idx, (header, _start, body_start) in enumerate(positions):
        end = positions[idx + 1][1] if idx + 1 < len(positions) else len(text)
        sections[header] = text[body_start:end].strip()
    return sections


def _scalar(body: str) -> str:
    """Return a single-line scalar value, blanking ``none`` sentinels."""
    value = " ".join(body.split()).strip()
    if value.lower() in _NONE_TOKENS:
        return ""
    return value


def _bullets(body: str) -> tuple[str, ...]:
    """Return bullet values, tolerating an inline ``none`` sentinel."""
    stripped = body.strip()
    if not stripped or stripped.lower() in _NONE_TOKENS:
        return ()
    items: list[str] = []
    matched = False
    for bullet in _BULLET.finditer(stripped):
        matched = True
        value = bullet.group("msg").strip()
        if value and value.lower() not in _NONE_TOKENS and value not in items:
            items.append(value)
    if matched:
        return tuple(items)
    # No bullets — treat a single inline line as one value.
    line = _scalar(stripped)
    return (line,) if line else ()
