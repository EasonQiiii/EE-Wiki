"""VLM extraction quality gate and OCR fallback for datasheet pages.

Complex table/graph pages can produce corrupted VLM markdown (empty cells,
truncated rows, garbled tokens). When heuristics fail and OCR text is richer,
prefer OCR as the page body so retrieval sees faithful content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.datasheet_pdf.classify import PageType

logger = get_logger(__name__)

_TABLE_ROW = re.compile(r"^\|(.+)\|$", re.MULTILINE)
# Markdown alignment row only (e.g. |---|:---:|---|) — not empty data cells
_SEPARATOR_ROW = re.compile(
    r"^\|\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|$",
    re.MULTILINE,
)
_GARBLE_RUN = re.compile(r"(.)\1{5,}")
_NON_WORD_CLUSTER = re.compile(r"[^\w\s|.\-:/()%°µΩ±≤≥≠×÷,+]{3,}", re.UNICODE)
_REPLACEMENT_CHAR = "\ufffd"


@dataclass(frozen=True)
class VlmQualityThresholds:
    """Configurable thresholds for the VLM quality gate.

    Attributes:
        enabled: When False, always keep VLM markdown (OCR appendix unchanged).
        max_empty_cell_ratio: Fail when markdown-table empty-cell ratio exceeds this.
        min_length_ratio: Fail when ``len(vlm) / len(ocr)`` is below this.
        max_garble_ratio: Fail when garbled-character ratio exceeds this.
        min_ocr_chars: Minimum OCR length required before OCR fallback is allowed.
        min_table_rows_vs_ocr_lines: Fail when VLM table rows are fewer than
            ``ocr_nonempty_lines * this`` (table/mixed pages only).
        apply_to_page_types: Page types subject to the gate (others keep VLM).
    """

    enabled: bool = True
    max_empty_cell_ratio: float = 0.45
    min_length_ratio: float = 0.25
    max_garble_ratio: float = 0.12
    min_ocr_chars: int = 80
    min_table_rows_vs_ocr_lines: float = 0.15
    apply_to_page_types: frozenset[str] = frozenset({"table", "graph", "mixed"})


@dataclass(frozen=True)
class VlmQualityScore:
    """Heuristic quality metrics for one page of VLM markdown.

    Attributes:
        passed: True when VLM output clears all enabled checks.
        reasons: Failure reason codes (empty when passed).
        empty_cell_ratio: Fraction of empty cells in detected markdown tables.
        table_row_count: Data rows counted (excludes separator rows).
        table_cell_count: Total data cells counted.
        length_ratio: ``len(vlm) / max(len(ocr), 1)``.
        garble_ratio: Estimated garbled-character fraction of VLM text.
        ocr_chars: Character count of OCR text.
        vlm_chars: Character count of VLM markdown.
        ocr_nonempty_lines: Non-empty OCR line count.
    """

    passed: bool
    reasons: tuple[str, ...]
    empty_cell_ratio: float
    table_row_count: int
    table_cell_count: int
    length_ratio: float
    garble_ratio: float
    ocr_chars: int
    vlm_chars: int
    ocr_nonempty_lines: int


def _split_cells(row_inner: str) -> list[str]:
    return [cell.strip() for cell in row_inner.split("|")]


def _table_stats(markdown: str) -> tuple[int, int, int, float]:
    """Return ``(row_count, cell_count, empty_cells, empty_ratio)`` for MD tables."""
    rows = 0
    cells = 0
    empty = 0
    for match in _TABLE_ROW.finditer(markdown):
        line = match.group(0).strip()
        if _SEPARATOR_ROW.match(line):
            continue
        row_cells = _split_cells(match.group(1))
        if not row_cells:
            continue
        rows += 1
        for cell in row_cells:
            cells += 1
            if not cell or cell in {"-", "—", "–", "n/a", "N/A", "NA"}:
                empty += 1
    ratio = (empty / cells) if cells else 0.0
    return rows, cells, empty, ratio


def _garble_ratio(text: str) -> float:
    """Estimate fraction of text that looks corrupted."""
    if not text:
        return 1.0
    bad = text.count(_REPLACEMENT_CHAR)
    for match in _GARBLE_RUN.finditer(text):
        bad += len(match.group(0))
    for match in _NON_WORD_CLUSTER.finditer(text):
        bad += len(match.group(0))
    # Dense pipes with almost no letters often indicate broken tables
    letters = sum(1 for ch in text if ch.isalpha())
    pipes = text.count("|")
    if pipes >= 20 and letters < pipes:
        bad += pipes - letters
    return min(1.0, bad / max(len(text), 1))


def _ocr_nonempty_lines(ocr_text: str) -> int:
    return sum(1 for line in ocr_text.splitlines() if line.strip())


def score_vlm_markdown(
    vlm_markdown: str,
    ocr_text: str,
    *,
    thresholds: VlmQualityThresholds | None = None,
) -> VlmQualityScore:
    """Score VLM page markdown against OCR using table/length/garble heuristics.

    Args:
        vlm_markdown: Markdown produced by the vision model for one page.
        ocr_text: Embedded/OCR text for the same page.
        thresholds: Optional gate thresholds (defaults when omitted).

    Returns:
        :class:`VlmQualityScore` with metrics and pass/fail plus reason codes.
    """
    cfg = thresholds or VlmQualityThresholds()
    vlm = (vlm_markdown or "").strip()
    ocr = (ocr_text or "").strip()
    vlm_chars = len(vlm)
    ocr_chars = len(ocr)
    length_ratio = vlm_chars / max(ocr_chars, 1)
    rows, cells, _empty, empty_ratio = _table_stats(vlm)
    garble = _garble_ratio(vlm)
    ocr_lines = _ocr_nonempty_lines(ocr)

    reasons: list[str] = []
    if not vlm:
        reasons.append("empty_vlm")
    if ocr_chars >= cfg.min_ocr_chars and length_ratio < cfg.min_length_ratio:
        reasons.append("short_vs_ocr")
    if cells >= 4 and empty_ratio > cfg.max_empty_cell_ratio:
        reasons.append("high_empty_cell_ratio")
    if garble > cfg.max_garble_ratio:
        reasons.append("high_garble_ratio")
    if (
        cells >= 2
        and ocr_lines >= 8
        and rows < max(2, int(ocr_lines * cfg.min_table_rows_vs_ocr_lines))
    ):
        reasons.append("low_row_count_vs_ocr")

    return VlmQualityScore(
        passed=not reasons,
        reasons=tuple(reasons),
        empty_cell_ratio=empty_ratio,
        table_row_count=rows,
        table_cell_count=cells,
        length_ratio=length_ratio,
        garble_ratio=garble,
        ocr_chars=ocr_chars,
        vlm_chars=vlm_chars,
        ocr_nonempty_lines=ocr_lines,
    )


def _ocr_is_richer(vlm_markdown: str, ocr_text: str, score: VlmQualityScore) -> bool:
    """Return True when OCR looks like a better primary body than VLM."""
    ocr = ocr_text.strip()
    vlm = vlm_markdown.strip()
    if not ocr:
        return False
    if not vlm:
        return True
    ocr_alnum = sum(1 for ch in ocr if ch.isalnum())
    vlm_alnum = sum(1 for ch in vlm if ch.isalnum())
    if ocr_alnum >= vlm_alnum and score.ocr_chars >= score.vlm_chars:
        return True
    if "short_vs_ocr" in score.reasons or "empty_vlm" in score.reasons:
        return score.ocr_chars > score.vlm_chars
    if "high_empty_cell_ratio" in score.reasons or "low_row_count_vs_ocr" in score.reasons:
        return score.ocr_chars >= int(score.vlm_chars * 0.8)
    if "high_garble_ratio" in score.reasons:
        return ocr_alnum > vlm_alnum
    return False


def select_page_markdown(
    *,
    vlm_markdown: str,
    ocr_text: str,
    page_type: PageType,
    page_num: int,
    thresholds: VlmQualityThresholds | None = None,
) -> tuple[str, VlmQualityScore | None]:
    """Choose VLM or OCR body for a classified datasheet page.

    Applies the quality gate only to configured page types (default:
    table/graph/mixed). When the gate fails and OCR is richer, returns OCR
    text as the page markdown.

    Args:
        vlm_markdown: Vision-model extraction for the page.
        ocr_text: Embedded/OCR text for the page.
        page_type: Classification from :func:`classify_page`.
        page_num: 0-based page index (for logging).
        thresholds: Optional quality-gate thresholds.

    Returns:
        ``(chosen_markdown, score_or_none)``. Score is ``None`` when the gate
        does not apply (disabled or page type excluded).
    """
    cfg = thresholds or VlmQualityThresholds()
    vlm = (vlm_markdown or "").strip()
    ocr = (ocr_text or "").strip()

    if not cfg.enabled or page_type.value not in cfg.apply_to_page_types:
        return vlm or ocr, None

    if len(ocr) < cfg.min_ocr_chars and vlm:
        score = score_vlm_markdown(vlm, ocr, thresholds=cfg)
        return vlm, score

    score = score_vlm_markdown(vlm, ocr, thresholds=cfg)
    if score.passed or not _ocr_is_richer(vlm, ocr, score):
        return vlm or ocr, score

    logger.info(
        "Datasheet VLM quality gate: preferring OCR for page %d "
        "(type=%s, reasons=%s, empty_cell_ratio=%.2f, length_ratio=%.2f, "
        "garble_ratio=%.2f, table_rows=%d, ocr_chars=%d, vlm_chars=%d)",
        page_num + 1,
        page_type.value,
        ",".join(score.reasons),
        score.empty_cell_ratio,
        score.length_ratio,
        score.garble_ratio,
        score.table_row_count,
        score.ocr_chars,
        score.vlm_chars,
    )
    return ocr, score
