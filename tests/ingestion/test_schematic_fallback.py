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


def test_fallback_uses_slug_subdirectory_in_image_paths() -> None:
    """Image references must include the slug subdirectory under images/."""
    layout = PageLayoutResult(
        page=3,
        raw_ocr_text="U15 MP2359 GND",
        crop_image_bytes=None,
        slice_filenames=["explorer_stm32f4_v2_2_sch_p3_crop_0.png"],
    )
    result = build_fallback_report(
        layout,
        project_id="logan",
        source_stem="Explorer STM32F4_V2.2_SCH",
    )
    expected = "images/explorer_stm32f4_v2_2_sch/explorer_stm32f4_v2_2_sch_p3_crop_0.png"
    assert expected in result.markdown


def test_fallback_includes_page_image() -> None:
    """When a page image is saved, it should appear in the fallback markdown."""
    layout = PageLayoutResult(
        page=1,
        raw_ocr_text="U1 VCC GND",
        crop_image_bytes=None,
        slice_filenames=[],
        page_image_filename="board_p1_page.png",
    )
    result = build_fallback_report(
        layout,
        project_id="logan",
        source_stem="board",
    )
    assert "images/board/board_p1_page.png" in result.markdown
    assert "整页电路图" in result.markdown
