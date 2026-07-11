"""Tests for datasheet Figure/Table query parsing and rank adjustment."""

from __future__ import annotations

from ee_wiki.retrieval.datasheet_query import (
    datasheet_rank_adjustment,
    expand_datasheet_query_tokens,
    parse_datasheet_query_hints,
)


def test_parse_figure_ref_without_page() -> None:
    hints = parse_datasheet_query_hints("STM32F407 Figure 58 描述什么")
    assert hints.figure_numbers == (58,)
    assert hints.explicit_page_numbers == ()


def test_parse_non_multiplexed_modifier() -> None:
    hints = parse_datasheet_query_hints(
        "Synchronous non-multiplexed NOR/PSRAM read timings"
    )
    assert "non-multiplexed" in hints.required_phrases
    assert hints.negated_variants == (("non-multiplexed", "multiplexed"),)


def test_expand_query_appends_figure_token() -> None:
    expanded = expand_datasheet_query_tokens("STM32F407 Figure 58")
    assert "Figure 58" in expanded


def test_penalize_page_chunk_for_figure_query() -> None:
    hints = parse_datasheet_query_hints("Figure 58")
    page_chunk = "## Page 58\n\n### Table 7. Alternate function mapping"
    score = datasheet_rank_adjustment(
        page_chunk,
        "STM32F407ZGT6__page-58__table-7",
        hints,
    )
    assert score < 0


def test_boost_figure_label_chunk() -> None:
    hints = parse_datasheet_query_hints("Figure 58")
    figure_chunk = (
        "### Page 134 OCR\n\nFigure 58.\n"
        "Synchronous non-multiplexed NOR/PSRAM read timings"
    )
    score = datasheet_rank_adjustment(
        figure_chunk,
        "STM32F407ZGT6__ocr-fidelity-appendix__page-134-ocr",
        hints,
    )
    assert score > 0


def test_penalize_multiplexed_when_query_requires_non() -> None:
    hints = parse_datasheet_query_hints("non-multiplexed NOR read timings")
    multiplexed = "## Page 131\n\n### Synchronous multiplexed NOR/PSRAM read timings"
    score = datasheet_rank_adjustment(
        multiplexed,
        "STM32F407ZGT6__page-131__synchronous-multiplexed-nor-psram-read-timings",
        hints,
    )
    assert score < 0
