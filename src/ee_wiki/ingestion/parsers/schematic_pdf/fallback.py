"""Rule-based fallback report when VLM extraction fails."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import (
    build_fidelity_appendix,
    extract_fidelity_fields,
    extract_fields_from_ocr,
)
from ee_wiki.ingestion.parsers.schematic_pdf.prompt import schematic_image_slug

__all__ = ["build_fallback_report", "extract_fields_from_ocr"]


def build_fallback_report(
    layout: PageLayoutResult,
    *,
    project_id: str,
    source_stem: str = "",
    images_rel_prefix: str = "images",
    connectivity_enabled: bool = True,
    max_connector_distance: float = 90.0,
    cad_extensions: tuple[str, ...] | None = None,
) -> PageExtraction:
    """Build a rule-based markdown report matching legacy temp3 fallback.

    Args:
        layout: Page layout analysis result.
        project_id: Project identifier for the report header.
        source_stem: Original PDF filename stem (used to derive the slug
            subdirectory under ``images/``).
        images_rel_prefix: Relative directory prefix for image references.
        connectivity_enabled: When True, use ADR 0007 module↔net ladder.
        max_connector_distance: PDF geometry catchment radius.
        cad_extensions: Companion CAD suffixes for discovery.
    """
    fields = extract_fidelity_fields(layout.raw_ocr_text)
    major_components = fields.major_components
    nets = fields.nets

    slug = schematic_image_slug(source_stem) if source_stem else ""
    slug_prefix = f"{images_rel_prefix}/{slug}" if slug else images_rel_prefix

    ics_str = (
        ", ".join(f"`{ic}`" for ic in major_components)
        if major_components
        else "未检测到主要 IC"
    )
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
{layout.raw_ocr_text[:400]}... (文本预览)
```

## 3. 相关电路图纸资产
"""
    if layout.page_image_filename:
        page_img = f"{slug_prefix}/{layout.page_image_filename}"
        markdown += f"![第 {layout.page} 页整页电路图]({page_img})\n\n"

    if layout.slice_filenames:
        markdown += "以下为系统通过 LayoutLMv3 自动裁剪出的核心电路高风险区域切片：\n\n"
        for filename in layout.slice_filenames:
            markdown += f"![{filename}]({slug_prefix}/{filename})\n"
            markdown += (
                "*VLM_Description: 芯片及其外围阻容滤波去耦网络局部。"
                "优先排查电源输入输出通路稳定性。*\n\n"
            )
    else:
        if not layout.page_image_filename:
            markdown += "*[未裁剪到有效的 Figure 区块]*\n"

    markdown += "\n\n" + build_fidelity_appendix(
        page=layout.page,
        raw_ocr_text=layout.raw_ocr_text,
        fields=fields,
        ocr_tokens=layout.ocr_tokens or None,
        source_pdf=layout.source_pdf,
        connectivity_enabled=connectivity_enabled,
        max_connector_distance=max_connector_distance,
        cad_extensions=cad_extensions,
    )

    return PageExtraction(
        page=layout.page,
        markdown=markdown.strip() + "\n",
        major_components=major_components,
        nets=nets,
        interfaces=fields.interfaces,
    )
