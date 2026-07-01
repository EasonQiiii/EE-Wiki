"""Tests for schematic PDF fallback report."""

from ee_wiki.ingestion.parsers.schematic_pdf.fallback import (
    build_fallback_report,
    extract_fields_from_ocr,
)
from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult


def test_extract_fields_from_ocr() -> None:
    text = "U101 connects VCC_3V3 and GND via R10 NRST"
    components, nets, _interfaces = extract_fields_from_ocr(text)
    assert "U101" in components
    assert "VCC_3V3" in nets or "GND" in nets


def test_build_fallback_report_includes_slices() -> None:
    layout = PageLayoutResult(
        page=2,
        raw_ocr_text="U1 VCC_3V3 GND",
        crop_image_bytes=None,
        slice_filenames=["board_p2_crop_0.png"],
    )
    result = build_fallback_report(layout, project_id="logan")
    assert "Page 2" in result.markdown
    assert "board_p2_crop_0.png" in result.markdown
    assert result.major_components
