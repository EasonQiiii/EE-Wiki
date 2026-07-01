"""Rule-based fallback report when VLM extraction fails."""

from __future__ import annotations

import re

from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction

_IC_PATTERN = re.compile(r"\b(U\d{1,4})\b")
_NET_PATTERN = re.compile(
    r"\b([A-Z0-9_]*VCC[A-Z0-9_]*|GND|MCU_[A-Z0-9_]+|NRST)\b",
    re.IGNORECASE,
)
_COMPONENT_PATTERN = re.compile(r"\b([URCLQD]\d{1,5})\b")
_EXTENDED_NET_PATTERN = re.compile(
    r"\b([A-Z0-9*]*VCC[A-Z0-9_]*|[A-Z0-9_]*VDD[A-Z0-9_]*|GND|MCU_[A-Z0-9_]+|NRST)\b",
    re.IGNORECASE,
)


def extract_fields_from_ocr(text: str) -> tuple[list[str], list[str], list[str]]:
    """Extract component and net lists from raw OCR text."""
    components = _dedupe(_COMPONENT_PATTERN.findall(text))
    major_components = [item for item in components if item.upper().startswith("U")]
    if not major_components:
        major_components = _dedupe(_IC_PATTERN.findall(text))
    nets = _dedupe(_EXTENDED_NET_PATTERN.findall(text))
    if not nets:
        nets = _dedupe(_NET_PATTERN.findall(text))
    interfaces = [net for net in nets if _looks_like_interface(net)]
    return major_components, nets, interfaces


def _looks_like_interface(net: str) -> bool:
    upper = net.upper()
    return any(key in upper for key in ("I2C", "SPI", "USB", "UART", "CAN", "RMII", "MDIO", "SWD", "JTAG"))


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def build_fallback_report(
    layout: PageLayoutResult,
    *,
    project_id: str,
    images_rel_prefix: str = "images",
) -> PageExtraction:
    """Build a rule-based markdown report matching legacy temp3 fallback."""
    text = layout.raw_ocr_text
    major_components, nets, _interfaces = extract_fields_from_ocr(text)

    ics_str = ", ".join(f"`{ic}`" for ic in major_components) if major_components else "未检测到主要 IC"
    nets_str = ", ".join(f"`{net}`" for net in nets[:10]) if nets else "未检测到核心网络"

    markdown = f"""# 电子图纸分析报告: {project_id} - [第 {layout.page} 页]

## 1. 模块图纸基本信息
* **图纸页码**: Page {layout.page}
* **主要芯片**: {ics_str}
* **核心网络**: {nets_str}

---

## 2. 拓扑结构与信号关联
* 提取出的文本流显示该区域包含以下元器件定义。
* 部分识别到的底层文本节点如下：

```text
{text[:400]}... (文本预览)
```

## 3. 相关电路图纸资产
"""
    if layout.slice_filenames:
        markdown += "以下为系统通过 LayoutLMv3 自动裁剪出的核心电路高风险区域切片：\n\n"
        for filename in layout.slice_filenames:
            markdown += f"![{filename}]({images_rel_prefix}/{filename})\n"
            markdown += "*VLM_Description: 芯片及其外围阻容滤波去耦网络局部。优先排查电源输入输出通路稳定性。*\n\n"
    else:
        markdown += "*[未裁剪到有效的 Figure 区块]*\n"

    return PageExtraction(
        page=layout.page,
        markdown=markdown.strip() + "\n",
        major_components=major_components,
        nets=nets,
        interfaces=[],
    )
