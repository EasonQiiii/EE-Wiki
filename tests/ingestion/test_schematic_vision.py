"""Tests for schematic vision response parsing."""

from ee_wiki.ingestion.parsers.schematic_pdf.vision import parse_page_response


def test_parse_page_response_json() -> None:
    text = """
    {
      "markdown": "## 1. 模块图纸基本信息\\n* **主要芯片**: `U101`\\n\\nU101 connects to `VBAT`",
      "major_components": ["U101"],
      "nets": ["VBAT"],
      "interfaces": []
    }
    """
    result = parse_page_response(text, page=3)
    assert result.page == 3
    assert "U101" in result.markdown
    assert "## 1." in result.markdown
    assert result.major_components == ["U101"]
    assert result.nets == ["VBAT"]


def test_parse_page_response_fenced_json() -> None:
    text = """Here is the result:
```json
{"markdown": "page text", "major_components": [], "nets": ["NET_A"], "interfaces": ["USB"]}
```"""
    result = parse_page_response(text, page=1)
    assert result.nets == ["NET_A"]
    assert result.interfaces == ["USB"]


def test_parse_page_response_markdown_with_meta_comment() -> None:
    text = """## 1. 模块图纸基本信息
* **主要芯片**: `U1`, `U2`

<!-- ee_wiki:major_components=U1,U2;nets=VCC_3V3;interfaces=I2C1 -->"""
    result = parse_page_response(text, page=2)
    assert "## 1." in result.markdown
    assert "ee_wiki" not in result.markdown
    assert result.major_components == ["U1", "U2"]
    assert result.nets == ["VCC_3V3"]
    assert result.interfaces == ["I2C1"]


def test_parse_page_response_truncated_json_extracts_markdown() -> None:
    """Regression: broken JSON must not be written verbatim to processed output."""
    text = (
        '{ "markdown": "## 1. 模块图纸基本信息\\n* **主要芯片**: `U1`\\n\\n'
        "## 2. 以太网 PHY (Ethernet PHY)\\n* **输入网络**: `VCC_3V3`"
    )
    result = parse_page_response(text, page=1)
    assert result.markdown.startswith("## 1.")
    assert not result.markdown.startswith("{")
    assert "U1" in result.markdown


def test_parse_page_response_truncates_repetition() -> None:
    chunk = "L2/GPIO2、R2/GPIO1、" * 20
    text = f"## 2. 音频接口\\n{chunk}"
    result = parse_page_response(text, page=1)
    assert result.markdown.count("L2/GPIO2") < 10
