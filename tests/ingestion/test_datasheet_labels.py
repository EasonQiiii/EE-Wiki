"""Tests for datasheet OCR Figure/Table label enrichment."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.datasheet_pdf.labels import (
    enrich_page_markdown_with_labels,
    extract_ocr_label_headings,
)


def test_extract_ocr_figure_and_table_labels() -> None:
    ocr = (
        "Electrical characteristics\n"
        "134/167\n"
        "Figure 58.\n"
        "Synchronous non-multiplexed NOR/PSRAM read timings\n"
        "         Table 77.\n"
        "Synchronous non-multiplexed NOR/PSRAM read timings(1)(2)\n"
    )
    labels = extract_ocr_label_headings(ocr)
    assert ("Figure 58", "Synchronous non-multiplexed NOR/PSRAM read timings") in labels
    assert any(item[0] == "Table 77" for item in labels)


def test_enrich_inserts_missing_figure_heading() -> None:
    ocr = "Figure 58.\nSynchronous non-multiplexed NOR/PSRAM read timings\n"
    markdown = "| Symbol | Parameter | Min | Max | Unit |"
    enriched = enrich_page_markdown_with_labels(markdown, ocr)
    assert "### Figure 58. Synchronous non-multiplexed NOR/PSRAM read timings" in enriched
    assert markdown in enriched


def test_enrich_skips_when_label_already_present() -> None:
    ocr = "Figure 58.\nSynchronous non-multiplexed NOR/PSRAM read timings\n"
    markdown = "### Figure 58. Synchronous non-multiplexed NOR/PSRAM read timings\n\nbody"
    assert enrich_page_markdown_with_labels(markdown, ocr) == markdown
