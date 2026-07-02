"""Tests for prose PDF parsing and ingest routing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.ingestion.parsers.prose_pdf import ProsePdfParserError, parse_prose_pdf
from ee_wiki.ingestion.parsers.prose_pdf.extract import extract_page_text
from ee_wiki.ingestion.pipeline import ingest_file
from ee_wiki.ingestion.sync import (
    collect_raw_files,
    expected_content_extension,
    is_ingestible_raw_file,
)


@pytest.fixture
def ingest_config(app_config, tmp_path: Path) -> AppConfig:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    layout = replace(
        app_config.data_layout,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )
    return replace(app_config, raw_dir=raw_dir, processed_dir=processed_dir, data_layout=layout)


def _mock_page(native_text: str) -> MagicMock:
    page = MagicMock()
    page.get_text.side_effect = lambda mode="text", textpage=None: native_text
    page.get_textpage_ocr.side_effect = AssertionError("OCR should not run")
    return page


def test_extract_page_text_uses_embedded_text_when_sufficient() -> None:
    page = _mock_page("Bring-up checklist for DUT power sequencing.")
    result = extract_page_text(
        page,
        page_num=1,
        min_text_chars=20,
        ocr_dpi=200,
        ocr_language="eng",
    )
    assert result.method == "text"
    assert "Bring-up checklist" in result.text


def test_extract_page_text_passes_tessdata_to_pymupdf() -> None:
    page = MagicMock()
    page.get_text.side_effect = lambda mode="text", textpage=None: "ab"
    textpage = MagicMock()
    page.get_textpage_ocr.return_value = textpage
    page.get_text.side_effect = lambda mode="text", textpage=None: (
        "OCR body with enough characters to be accepted."
        if textpage is not None
        else "ab"
    )

    result = extract_page_text(
        page,
        page_num=1,
        min_text_chars=20,
        ocr_dpi=200,
        ocr_language="eng",
        tessdata_dir="/opt/homebrew/share/tessdata",
    )
    assert result.method == "ocr"
    page.get_textpage_ocr.assert_called_once_with(
        dpi=200,
        full=True,
        language="eng",
        tessdata="/opt/homebrew/share/tessdata",
    )


def test_extract_page_text_falls_back_to_ocr_when_sparse() -> None:
    page = MagicMock()
    page.get_text.side_effect = lambda mode="text", textpage=None: (
        "Scanned SOP page content from OCR."
        if textpage is not None
        else "ab"
    )
    textpage = MagicMock()
    page.get_textpage_ocr.return_value = textpage

    result = extract_page_text(
        page,
        page_num=2,
        min_text_chars=20,
        ocr_dpi=200,
        ocr_language="eng",
        tessdata_dir="/opt/homebrew/share/tessdata",
    )
    assert result.method == "ocr"
    assert "Scanned SOP" in result.text
    page.get_textpage_ocr.assert_called_once_with(
        dpi=200,
        full=True,
        language="eng",
        tessdata="/opt/homebrew/share/tessdata",
    )


def test_parse_prose_pdf_builds_page_sections(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/sop/bringup.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    mock_doc = MagicMock()
    mock_doc.page_count = 2
    mock_doc.__getitem__.side_effect = lambda index: _mock_page(
        f"Page {index + 1} body with enough embedded text for extraction."
    )
    mock_doc.__enter__ = MagicMock(return_value=mock_doc)
    mock_doc.__exit__ = MagicMock(return_value=False)

    with patch("ee_wiki.ingestion.parsers.prose_pdf.fitz.open", return_value=mock_doc):
        document = parse_prose_pdf(raw_path, ingest_config.data_layout, ingest_config)

    assert document.metadata.document_type == "sop"
    assert document.metadata.page == 2
    assert "# bringup" in document.content.lower() or "# Bringup" in document.content
    assert "## Page 1" in document.content
    assert "## Page 2" in document.content
    assert "Page 1 body" in document.content


def test_ingest_file_prose_pdf_end_to_end(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "global/datasheet/tps62840.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    mock_doc = MagicMock()
    mock_doc.page_count = 1
    mock_doc.__getitem__.return_value = _mock_page(
        "TPS62840 3A step-down converter electrical characteristics table."
    )

    with patch("ee_wiki.ingestion.parsers.prose_pdf.fitz.open", return_value=mock_doc):
        result = ingest_file(raw_path, ingest_config)

    assert result.processed.content_path.suffix == ".md"
    assert result.processed.content_path.exists()
    assert "TPS62840" in result.processed.content_path.read_text(encoding="utf-8")
    assert result.document.metadata.document_type == "datasheet"


def test_parse_prose_pdf_rejects_schematic_path(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/sch/board.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")
    with pytest.raises(ProsePdfParserError, match="sch/"):
        parse_prose_pdf(raw_path, ingest_config.data_layout, ingest_config)


def test_sync_treats_prose_pdf_as_ingestible(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/note/scan.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    assert is_ingestible_raw_file(raw_path, ingest_config.data_layout)
    assert expected_content_extension(raw_path, ingest_config.data_layout) == ".md"
    assert collect_raw_files(ingest_config.raw_dir, ingest_config.data_layout) == [raw_path]


def test_parse_prose_pdf_raises_when_no_text(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/note/empty.pdf"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"%PDF-1.4")

    mock_doc = MagicMock()
    mock_doc.page_count = 1
    page = MagicMock()
    page.get_text.return_value = ""
    page.get_textpage_ocr.side_effect = RuntimeError("tesseract not installed")
    mock_doc.__getitem__.return_value = page

    with (
        patch("ee_wiki.ingestion.parsers.prose_pdf.fitz.open", return_value=mock_doc),
        pytest.raises(ProsePdfParserError, match="tesseract not installed"),
    ):
        parse_prose_pdf(raw_path, ingest_config.data_layout, ingest_config)
