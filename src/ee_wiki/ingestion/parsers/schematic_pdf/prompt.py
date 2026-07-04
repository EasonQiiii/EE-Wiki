"""Prompt templates for schematic PDF vision extraction (temp3.py pipeline)."""

from __future__ import annotations

import re

SCHEMATIC_SYSTEM_PROMPT = (
    "你是一个资深的硬件研发专家与失效分析 (FA) 专家。你的任务是分析输入的电路图原始文本"
    "以及裁剪出的局部电路图。你需要将杂乱无章的元器件信息重构成一份结构极其专业、"
    "排版优美的硬件分析 Markdown 报告。请使用标准的 Markdown 语法（如标题、列表、引用块），"
    "报告中需指明主要芯片、核心电源/信号拓扑、关键引脚的网络映射关系，"
    "并结合你在失效分析领域的深厚积累，提供一条高价值的 FA 经验排查备注。"
)


def schematic_image_slug(source_stem: str) -> str:
    """Normalize a PDF filename stem for crop image filenames."""
    slug = source_stem.lower().replace(" ", "_")
    return re.sub(r"[^\w\-]+", "_", slug).strip("_") or "schematic"


def build_schematic_page_prompt(
    *,
    page: int,
    project_id: str,
    raw_ocr_text: str,
    ocr_text_max_chars: int = 1200,
    slice_filenames: list[str] | None = None,
    page_image_filename: str = "",
    images_rel_prefix: str = "images",
    source_stem: str = "",
) -> str:
    """Build the user prompt for Qwen3-VL page reconstruction."""
    preview = raw_ocr_text[:ocr_text_max_chars]
    slug = schematic_image_slug(source_stem) if source_stem else ""
    slug_prefix = f"{images_rel_prefix}/{slug}" if slug else images_rel_prefix

    asset_hint = ""
    asset_lines_parts: list[str] = []
    if page_image_filename:
        asset_lines_parts.append(f"- `{slug_prefix}/{page_image_filename}` (整页电路图)")
    if slice_filenames:
        asset_lines_parts.extend(
            f"- `{slug_prefix}/{name}`" for name in slice_filenames
        )
    if asset_lines_parts:
        asset_lines = "\n".join(asset_lines_parts)
        asset_hint = (
            f"\n【已裁剪局部电路图】\n{asset_lines}\n"
            "请在报告第 3 或第 4 节用 Markdown 图片语法 "
            "`![描述](路径)` 引用上述图片路径，并补充 VLM_Description。\n"
        )

    return (
        "请分析以下提供的 PDF 原始提取文本，并结合上传的局部核心电路切片图片，"
        "将其重构成一份极其精美的硬件分析报告 Markdown 篇章。\n\n"
        f"【本页图纸基本信息】:\n页码: Page {page}\n项目代号: {project_id}\n"
        f"{asset_hint}\n"
        f"【PDF 原始提取文本】:\n{preview}\n\n"
        "【输出要求】\n"
        "1. 只输出 Markdown，不要 JSON，不要用代码围栏包裹全文。\n"
        "2. 建议结构：\n"
        "   ## 1. 模块图纸基本信息\n"
        "   ## 2. 拓扑结构与信号关联（或电源/接口等实际主题）\n"
        "   ## 3. MCU/关键芯片引脚网络映射（若适用）\n"
        "   ## 4. 相关电路图纸资产（引用已裁剪图片路径）\n"
        "3. 位号与网络名必须与 OCR 文本及图片一致，禁止编造。\n"
        "4. 可加入 `> [!NOTE]` FA 经验备注。\n"
    )
