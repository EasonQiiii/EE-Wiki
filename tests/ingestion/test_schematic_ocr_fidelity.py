"""Tests for OCR fidelity schematic extraction."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import (
    build_fidelity_extraction,
    extract_fidelity_fields,
    extract_module_labels,
)


def test_extract_module_labels_finds_oled_camera() -> None:
    text = "CAN&USB\nEEPROM\nOLED&CAMERA\nLED\nU10\n"
    labels = extract_module_labels(text)
    assert "OLED&CAMERA" in labels
    assert "U10" not in labels


def test_extract_fidelity_fields_finds_dcmi_nets() -> None:
    text = "OLED&CAMERA\nNLDCMI0D0\nPIP809NLDCMI0D1\nDCMI__SCL\nGND\n"
    fields = extract_fidelity_fields(text)
    assert "OLED&CAMERA" in fields.module_labels
    assert "DCMI_D0" in fields.nets
    assert "DCMI_SCL" in fields.nets


def test_build_fidelity_extraction_includes_page_signal_summary() -> None:
    layout = PageLayoutResult(
        page=3,
        raw_ocr_text="OLED&CAMERA\nDCMI_D0\nDCMI_D1\nDCMI_SCL\n",
        crop_image_bytes=None,
        slice_filenames=[],
    )
    result = build_fidelity_extraction(layout, project_id="demo")
    assert "OLED&CAMERA" in result.markdown
    assert "DCMI_D0" in result.markdown
    assert "本页模块与接口信号" in result.markdown
    assert "OCR 保真摘录" in result.markdown


def test_enrich_with_fidelity_skips_duplicate_appendix() -> None:
    from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
    from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
    from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import enrich_with_fidelity

    layout = PageLayoutResult(
        page=2,
        raw_ocr_text="OLED&CAMERA\nDCMI_D0\n",
        crop_image_bytes=None,
        slice_filenames=[],
    )
    existing = PageExtraction(
        page=2,
        markdown="## fallback\n\n## 5. OCR 保真摘录（检索依据，禁止改写）\n",
        major_components=[],
        nets=[],
        interfaces=[],
    )
    enriched = enrich_with_fidelity(existing, layout)
    assert enriched.markdown.count("## 5. OCR 保真摘录") == 1
    assert "DCMI_D0" in enriched.nets
