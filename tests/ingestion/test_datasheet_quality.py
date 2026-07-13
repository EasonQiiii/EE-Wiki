"""Unit tests for datasheet VLM quality gate and OCR fallback."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.datasheet_pdf.classify import PageType
from ee_wiki.ingestion.parsers.datasheet_pdf.quality import (
    VlmQualityThresholds,
    score_vlm_markdown,
    select_page_markdown,
)

_GOOD_OCR = "\n".join(
    [
        "Table 77.",
        "Synchronous multiplexed NOR/PSRAM read timings",
        "Symbol Parameter Min Typ Max Unit",
        "tacc Address setup time 1 2 3 ns",
        "tw Data hold time 4 5 6 ns",
        "FSMC_D[15:0] data bus",
        "CLK rising edge",
        "NADV low pulse",
        "line nine more timing text",
        "line ten with extra tokens for length",
    ]
)


def _corrupted_table_vlm() -> str:
    """Synthetic VLM output with many empty cells (page-131 style)."""
    rows = [
        "| Symbol | Parameter | Min | Typ | Max | Unit |",
        "|---|---|---|---|---|---|",
        "|  |  |  |  |  |  |",
        "|  |  |  |  |  |  |",
        "| A |  |  |  |  |  |",
        "|  |  |  |  |  |  |",
    ]
    return "\n".join(rows)


def test_score_flags_high_empty_cell_ratio() -> None:
    score = score_vlm_markdown(_corrupted_table_vlm(), _GOOD_OCR)
    assert not score.passed
    assert "high_empty_cell_ratio" in score.reasons
    assert score.empty_cell_ratio > 0.45


def test_score_flags_short_vs_ocr() -> None:
    vlm = "| A | B |\n|---|---|\n| 1 | 2 |"
    score = score_vlm_markdown(vlm, _GOOD_OCR * 3)
    assert not score.passed
    assert "short_vs_ocr" in score.reasons


def test_score_flags_garble() -> None:
    vlm = "xxxxxx!!!!!!@@@###" * 20 + "\n| a | b |\n|---|---|\n| 1 | 2 |"
    score = score_vlm_markdown(vlm, _GOOD_OCR)
    assert not score.passed
    assert "high_garble_ratio" in score.reasons


def test_score_passes_clean_table() -> None:
    vlm = "\n".join(
        [
            "### Table 77. Synchronous multiplexed NOR/PSRAM read timings",
            "",
            "| Symbol | Parameter | Min | Typ | Max | Unit |",
            "|---|---|---|---|---|---|",
            "| tacc | Address setup | 1 | 2 | 3 | ns |",
            "| tw | Data hold | 4 | 5 | 6 | ns |",
            "| tsu | Setup time | 7 | 8 | 9 | ns |",
            "| th | Hold time | 1 | 1 | 2 | ns |",
        ]
    )
    score = score_vlm_markdown(vlm, _GOOD_OCR)
    assert score.passed
    assert score.reasons == ()


def test_select_prefers_ocr_when_vlm_corrupted() -> None:
    chosen, score = select_page_markdown(
        vlm_markdown=_corrupted_table_vlm(),
        ocr_text=_GOOD_OCR,
        page_type=PageType.TABLE,
        page_num=130,
    )
    assert score is not None
    assert not score.passed
    assert chosen == _GOOD_OCR.strip()
    assert "FSMC_D[15:0]" in chosen


def test_select_keeps_vlm_when_quality_ok() -> None:
    vlm = "\n".join(
        [
            "| Symbol | Parameter | Min | Max | Unit |",
            "|---|---|---|---|---|",
            "| tacc | Address setup | 1 | 3 | ns |",
            "| tw | Data hold | 4 | 6 | ns |",
            "| tsu | Setup | 7 | 9 | ns |",
            "| th | Hold | 1 | 2 | ns |",
            "| tcy | Cycle | 10 | 12 | ns |",
        ]
    )
    chosen, score = select_page_markdown(
        vlm_markdown=vlm,
        ocr_text=_GOOD_OCR,
        page_type=PageType.TABLE,
        page_num=10,
    )
    assert score is not None
    assert score.passed
    assert "Address setup" in chosen
    assert chosen.startswith("| Symbol")


def test_select_skips_gate_for_text_pages() -> None:
    chosen, score = select_page_markdown(
        vlm_markdown="short",
        ocr_text=_GOOD_OCR,
        page_type=PageType.TEXT,
        page_num=0,
    )
    assert score is None
    assert chosen == "short"


def test_select_respects_disabled_gate() -> None:
    thresholds = VlmQualityThresholds(enabled=False)
    chosen, score = select_page_markdown(
        vlm_markdown=_corrupted_table_vlm(),
        ocr_text=_GOOD_OCR,
        page_type=PageType.TABLE,
        page_num=130,
        thresholds=thresholds,
    )
    assert score is None
    assert chosen == _corrupted_table_vlm().strip()


def test_select_keeps_vlm_when_ocr_too_short() -> None:
    thresholds = VlmQualityThresholds(min_ocr_chars=500)
    vlm = _corrupted_table_vlm()
    chosen, score = select_page_markdown(
        vlm_markdown=vlm,
        ocr_text="tiny ocr",
        page_type=PageType.MIXED,
        page_num=5,
        thresholds=thresholds,
    )
    assert score is not None
    assert chosen == vlm.strip()


def test_select_falls_back_on_empty_vlm() -> None:
    chosen, score = select_page_markdown(
        vlm_markdown="",
        ocr_text=_GOOD_OCR,
        page_type=PageType.GRAPH,
        page_num=40,
    )
    assert score is not None
    assert "empty_vlm" in score.reasons
    assert chosen == _GOOD_OCR.strip()
