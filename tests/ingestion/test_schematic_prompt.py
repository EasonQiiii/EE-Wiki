"""Tests for schematic PDF vision prompts (temp3.py)."""

from ee_wiki.ingestion.parsers.schematic_pdf.prompt import (
    SCHEMATIC_SYSTEM_PROMPT,
    build_schematic_page_prompt,
    schematic_image_slug,
)


def test_schematic_image_slug() -> None:
    assert schematic_image_slug("Board Rev A V1.0_SCH") == "board_rev_a_v1_0_sch"


def test_build_schematic_page_prompt_includes_ocr_and_project() -> None:
    prompt = build_schematic_page_prompt(
        page=2,
        project_id="demo_proj",
        raw_ocr_text="U1 IFACE_CHIP VCC_3V3",
        slice_filenames=["board_p2_crop_0.png"],
    )
    assert "Page 2" in prompt
    assert "demo_proj" in prompt
    assert "U1 IFACE_CHIP" in prompt
    assert "board_p2_crop_0.png" in prompt
    assert "PDF 原始提取文本" in prompt


def test_system_prompt_fa_expert() -> None:
    assert "失效分析" in SCHEMATIC_SYSTEM_PROMPT
    assert "Markdown" in SCHEMATIC_SYSTEM_PROMPT
