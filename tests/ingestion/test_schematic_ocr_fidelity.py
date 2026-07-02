"""Tests for OCR fidelity schematic extraction."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import (
    build_fidelity_extraction,
    extract_fidelity_fields,
    extract_module_labels,
)

_MODULE_A = "DISPLAY&SENSOR"
_NET_A0 = "IFACE_D0"
_NET_A1 = "IFACE_D1"
_NET_A_SCL = "IFACE_SCL"


def test_extract_module_labels_finds_ampersand_zone_labels() -> None:
    text = "COMM&USB\nEEPROM\nDISPLAY&SENSOR\nLED\nU10\n"
    labels = extract_module_labels(text)
    assert _MODULE_A in labels
    assert "U10" not in labels


def test_extract_fidelity_fields_recovers_embedded_nets() -> None:
    text = f"{_MODULE_A}\nNLIFACE0D0\nPIP809NLIFACE0D1\nIFACE__SCL\nGND\n"
    fields = extract_fidelity_fields(text)
    assert _MODULE_A in fields.module_labels
    assert _NET_A0 in fields.nets
    assert _NET_A_SCL in fields.nets


def test_build_fidelity_extraction_includes_page_signal_summary() -> None:
    layout = PageLayoutResult(
        page=3,
        raw_ocr_text=f"{_MODULE_A}\n{_NET_A0}\n{_NET_A1}\n{_NET_A_SCL}\n",
        crop_image_bytes=None,
        slice_filenames=[],
    )
    result = build_fidelity_extraction(layout, project_id="demo")
    assert _MODULE_A in result.markdown
    assert _NET_A0 in result.markdown
    assert "本页模块与接口信号" in result.markdown
    assert "OCR 保真摘录" in result.markdown


def test_enrich_with_fidelity_skips_duplicate_appendix() -> None:
    from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
    from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import enrich_with_fidelity

    layout = PageLayoutResult(
        page=2,
        raw_ocr_text=f"{_MODULE_A}\n{_NET_A0}\n",
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
    assert _NET_A0 in enriched.nets
