"""Tests for schematic page merge logic."""

from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction, merge_page_extractions


def test_merge_page_extractions_dedupes_fields() -> None:
    pages = [
        PageExtraction(
            page=1,
            markdown="Block A",
            major_components=["U1", "R2"],
            nets=["VBAT"],
            interfaces=["I2C"],
        ),
        PageExtraction(
            page=2,
            markdown="Block B",
            major_components=["U1", "C3"],
            nets=["VBAT", "GND"],
            interfaces=[],
        ),
    ]
    markdown, components, nets, interfaces = merge_page_extractions(pages, title="main")
    assert "# 电子图纸分析报告：main" in markdown
    assert "Block A" in markdown
    assert "Block B" in markdown
    assert "---" in markdown
    assert components == ["U1", "R2", "C3"]
    assert nets == ["VBAT", "GND"]
    assert interfaces == ["I2C"]
