"""Tests for prose PDF OCR language auto-detection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ee_wiki.ingestion.parsers.prose_pdf.language import (
    cjk_character_ratio,
    detect_language_from_osd,
    language_from_text_sample,
    resolve_document_ocr_language,
    resolve_page_ocr_language,
)


def test_cjk_character_ratio_detects_chinese_text() -> None:
    assert cjk_character_ratio("Bring-up 上电流程 for DUT") > 0.1


def test_language_from_text_sample_uses_bilingual_for_chinese() -> None:
    assert language_from_text_sample("工程笔记：DUT 上电顺序") == "eng+chi_sim"


def test_language_from_text_sample_uses_english_for_latin_only() -> None:
    assert language_from_text_sample("Bring-up checklist for DUT power sequencing.") == "eng"


def test_resolve_document_ocr_language_auto_from_embedded_chinese() -> None:
    document = MagicMock()
    document.__getitem__.return_value.get_text.return_value = "工程 SOP：DUT 上电流程说明"

    resolved = resolve_document_ocr_language(
        document,
        page_limit=1,
        configured_language="auto",
        fallback_language="eng+chi_sim",
        ocr_dpi=200,
    )
    assert resolved == "eng+chi_sim"


def test_resolve_document_ocr_language_auto_from_embedded_english() -> None:
    document = MagicMock()
    document.__getitem__.return_value.get_text.return_value = "Bring-up checklist for DUT power."

    resolved = resolve_document_ocr_language(
        document,
        page_limit=1,
        configured_language="auto",
        fallback_language="eng+chi_sim",
        ocr_dpi=200,
    )
    assert resolved == "eng"


def test_resolve_document_ocr_language_respects_explicit_setting() -> None:
    document = MagicMock()
    resolved = resolve_document_ocr_language(
        document,
        page_limit=1,
        configured_language="eng+chi_sim",
        fallback_language="eng",
        ocr_dpi=200,
    )
    assert resolved == "eng+chi_sim"
    document.__getitem__.assert_not_called()


def test_resolve_document_ocr_language_uses_osd_for_image_only_pdf() -> None:
    document = MagicMock()
    document.__getitem__.return_value.get_text.return_value = ""

    with patch(
        "ee_wiki.ingestion.parsers.prose_pdf.language.detect_language_from_osd",
        return_value="eng+chi_sim",
    ) as osd:
        resolved = resolve_document_ocr_language(
            document,
            page_limit=1,
            configured_language="auto",
            fallback_language="eng",
            ocr_dpi=200,
        )

    assert resolved == "eng+chi_sim"
    osd.assert_called_once()


def test_resolve_document_ocr_language_uses_fallback_when_osd_missing() -> None:
    document = MagicMock()
    document.__getitem__.return_value.get_text.return_value = ""

    with patch(
        "ee_wiki.ingestion.parsers.prose_pdf.language.detect_language_from_osd",
        return_value=None,
    ):
        resolved = resolve_document_ocr_language(
            document,
            page_limit=1,
            configured_language="auto",
            fallback_language="eng+chi_sim",
            ocr_dpi=200,
        )

    assert resolved == "eng+chi_sim"


def test_resolve_page_ocr_language_overrides_sparse_chinese_snippet() -> None:
    page = MagicMock()
    page.get_text.return_value = "工程"

    resolved = resolve_page_ocr_language(
        page,
        configured_language="auto",
        document_language="eng",
    )
    assert resolved == "eng+chi_sim"


def test_detect_language_from_osd_maps_han_script() -> None:
    page = MagicMock()
    with (
        patch(
            "ee_wiki.ingestion.parsers.prose_pdf.language.resolve_tesseract_binary",
            return_value="/opt/homebrew/bin/tesseract",
        ),
        patch("ee_wiki.ingestion.parsers.prose_pdf.language.subprocess.run") as run,
        patch("ee_wiki.ingestion.parsers.prose_pdf.language.fitz", create=True),
    ):
        run.return_value = MagicMock(
            returncode=0,
            stdout="Script: Han\nScript confidence: 7.0\n",
            stderr="",
        )
        page.get_pixmap.return_value.save = MagicMock()
        assert detect_language_from_osd(page, ocr_dpi=200) == "eng+chi_sim"
