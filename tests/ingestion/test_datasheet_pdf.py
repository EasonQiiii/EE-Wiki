"""Tests for datasheet PDF parser — classification, prompts, and dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from ee_wiki.ingestion.parsers.datasheet_pdf.classify import (
    PageType,
    classify_page,
)
from ee_wiki.ingestion.parsers.datasheet_pdf.merge import PageResult, merge_pages
from ee_wiki.ingestion.parsers.datasheet_pdf.prompts import (
    build_graph_prompt,
    build_mixed_prompt,
    build_table_prompt,
)

# --- Classification tests ---


def _mock_page(*, text: str, drawings: list | None = None, images: list | None = None):
    """Build a mock fitz.Page with configurable text, drawings, and images."""
    page = MagicMock()
    page.get_text.return_value = text
    page.get_drawings.return_value = drawings or []
    page.get_image_info.return_value = images or []
    page.rect = MagicMock()
    page.rect.width = 612.0
    page.rect.height = 792.0
    return page


def test_classify_text_page() -> None:
    page = _mock_page(text="A" * 600, drawings=[], images=[])
    clf = classify_page(page, 0)
    assert clf.page_type == PageType.TEXT
    assert clf.text_chars == 600


def test_classify_table_page_by_vector_lines() -> None:
    drawings = [{"items": [("l",)] * 10} for _ in range(6)]
    page = _mock_page(text="Parameter Min Typ Max", drawings=drawings)
    clf = classify_page(page, 1)
    assert clf.page_type == PageType.TABLE


def test_classify_graph_page_by_image_area() -> None:
    images = [{"bbox": (0, 0, 600, 700)}]
    page = _mock_page(text="", drawings=[], images=images)
    clf = classify_page(page, 2)
    assert clf.page_type == PageType.GRAPH
    assert clf.image_area_ratio > 0.6


def test_classify_mixed_page() -> None:
    page = _mock_page(text="Some text" * 10, drawings=[{"items": [("l",)] * 3}])
    clf = classify_page(page, 3)
    assert clf.page_type == PageType.MIXED


# --- Prompt tests ---


def test_table_prompt_includes_ocr_context() -> None:
    prompt = build_table_prompt("AMS1117 Electrical Characteristics")
    assert "AMS1117" in prompt
    assert "Markdown table" in prompt


def test_table_prompt_without_ocr() -> None:
    prompt = build_table_prompt(None)
    assert "OCR text" not in prompt
    assert "Markdown table" in prompt


def test_graph_prompt_includes_ocr_labels() -> None:
    prompt = build_graph_prompt("Temperature Stability\nTEMPERATURE (°C)")
    assert "Temperature Stability" in prompt
    assert "trend" in prompt


def test_mixed_prompt_includes_instructions() -> None:
    prompt = build_mixed_prompt("mixed content")
    assert "tables" in prompt.lower()
    assert "graphs" in prompt.lower() or "charts" in prompt.lower()


# --- Merge tests ---


def test_merge_pages_includes_all_sections() -> None:
    pages = [
        PageResult(
            page_num=0,
            markdown="## Features\n\nLow dropout",
            ocr_text="Features Low dropout",
        ),
        PageResult(
            page_num=1,
            markdown="| Param | Min | Max |\n|---|---|---|",
            ocr_text="Param Min Max",
        ),
    ]
    result = merge_pages("AMS1117", pages, ocr_fidelity=True)
    assert "# AMS1117" in result
    assert "## Page 1" in result
    assert "## Page 2" in result
    assert "Low dropout" in result
    assert "OCR Fidelity Appendix" in result


def test_merge_pages_without_ocr_fidelity() -> None:
    pages = [PageResult(page_num=0, markdown="content", ocr_text="raw text")]
    result = merge_pages("test", pages, ocr_fidelity=False)
    assert "OCR Fidelity" not in result
    assert "content" in result


def test_merge_pages_enriches_figure_label_from_ocr() -> None:
    pages = [
        PageResult(
            page_num=133,
            markdown="| Symbol | Parameter | Min | Max | Unit |",
            ocr_text=(
                "Figure 58.\n"
                "Synchronous non-multiplexed NOR/PSRAM read timings\n"
            ),
        ),
    ]
    result = merge_pages("STM32F407ZGT6", pages, ocr_fidelity=True)
    assert "### Figure 58. Synchronous non-multiplexed NOR/PSRAM read timings" in result
    assert "## Page 134" in result


# --- Dispatch test ---


def test_datasheet_dispatch_routes_to_datasheet_parser(tmp_path: Path) -> None:
    """Verify that PDFs in datasheet/ folder route to datasheet parser."""
    from ee_wiki.common.config import load_config

    config = load_config()
    raw_path = config.raw_dir / "global/datasheet/test.pdf"

    from ee_wiki.ingestion.path_metadata import parse_path_metadata

    metadata = parse_path_metadata(raw_path, config.data_layout, repo_root=config.repo_root)
    assert metadata.document_type == "datasheet"
