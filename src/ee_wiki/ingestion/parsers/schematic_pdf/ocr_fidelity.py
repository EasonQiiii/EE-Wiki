"""Lossless OCR extraction for schematic PDF pages."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
from ee_wiki.ingestion.parsers.schematic_pdf.signals import (
    build_page_signal_summary,
    normalize_ocr_text,
    recover_noisy_prefix_nets,
)

_COMPONENT_PATTERN = re.compile(r"\b([URCLQD]\d{1,5})\b")
_IC_PATTERN = re.compile(r"\b(U\d{1,4})\b")
_POWER_NET_PATTERN = re.compile(
    r"\b([A-Z0-9*]*VCC[A-Z0-9_]*|[A-Z0-9_]*VDD[A-Z0-9_]*|GND|AGND|NRST)\b",
    re.IGNORECASE,
)
_NAMED_NET_PATTERN = re.compile(
    r"\b([A-Z][A-Z0-9]{0,15}_[A-Z0-9][A-Z0-9_]{0,31})\b",
    re.IGNORECASE,
)
_MODULE_LABEL_PATTERN = re.compile(r"^[A-Z][A-Z0-9 &/+-]{2,48}$")
_SKIP_MODULE_LABELS = frozenset(
    {
        "TITLE",
        "AUTHOR",
        "DATE",
        "SIZE",
        "REVISION",
        "FILE",
        "VERSION",
        "GND",
        "VCC",
        "AGND",
        "PHONE",
        "LINE_IN",
        "SHEETSIZE",
        "BOOT0",
        "RESET",
    }
)


@dataclass(frozen=True)
class FidelityFields:
    """Structured values extracted from full-page OCR text."""

    major_components: list[str]
    nets: list[str]
    interfaces: list[str]
    module_labels: list[str]


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


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        merged.extend(group)
    return _dedupe(merged)


def _is_module_zone_label(candidate: str) -> bool:
    """Keep schematic zone titles using structural rules only."""
    if "&" in candidate or "/" in candidate:
        return True
    return " " in candidate and len(candidate) >= 8


def _is_component_ref(token: str) -> bool:
    return bool(_COMPONENT_PATTERN.fullmatch(token))


def extract_schematic_nets(text: str) -> list[str]:
    """Extract schematic net names from OCR text."""
    normalized = normalize_ocr_text(text)
    nets: set[str] = set(_NAMED_NET_PATTERN.findall(normalized))
    nets.update(_POWER_NET_PATTERN.findall(normalized))
    nets.update(recover_noisy_prefix_nets(normalized))
    nets = {net for net in nets if not _is_component_ref(net)}
    return sorted(nets, key=lambda value: value.upper())


def extract_module_labels(text: str) -> list[str]:
    """Extract schematic module zone labels such as ``DISPLAY&SENSOR``."""
    labels: list[str] = []
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate or len(candidate) > 48:
            continue
        if not _MODULE_LABEL_PATTERN.match(candidate):
            continue
        upper = candidate.upper()
        if upper in _SKIP_MODULE_LABELS:
            continue
        if _is_component_ref(candidate):
            continue
        if candidate.isdigit():
            continue
        if not _is_module_zone_label(candidate):
            continue
        labels.append(candidate)
    return _dedupe(labels)


def extract_fidelity_fields(text: str) -> FidelityFields:
    """Extract searchable metadata from full-page OCR without VLM rewriting."""
    components = _dedupe(_COMPONENT_PATTERN.findall(text))
    major_components = [item for item in components if item.upper().startswith("U")]
    if not major_components:
        major_components = _dedupe(_IC_PATTERN.findall(text))

    nets = extract_schematic_nets(text)
    module_labels = extract_module_labels(text)
    interfaces = _dedupe([*module_labels, *[net.split("_", 1)[0] for net in nets if "_" in net]])
    return FidelityFields(
        major_components=major_components,
        nets=nets,
        interfaces=interfaces,
        module_labels=module_labels,
    )


def extract_fields_from_ocr(text: str) -> tuple[list[str], list[str], list[str]]:
    """Backward-compatible wrapper around :func:`extract_fidelity_fields`."""
    fields = extract_fidelity_fields(text)
    return fields.major_components, fields.nets, fields.interfaces


def _page_summary_block(fields: FidelityFields, raw_ocr_text: str) -> str:
    summary = build_page_signal_summary(
        fields.module_labels,
        fields.nets,
        ocr_text=raw_ocr_text,
        heading_level=3,
    )
    return f"\n\n{summary}" if summary else ""


def build_fidelity_appendix(
    *,
    page: int,
    raw_ocr_text: str,
    fields: FidelityFields | None = None,
) -> str:
    """Build a lossless OCR appendix for one schematic page."""
    fidelity = fields or extract_fidelity_fields(raw_ocr_text)
    module_lines = (
        "\n".join(f"- `{label}`" for label in fidelity.module_labels)
        or "- （未识别到模块分区标签）"
    )
    net_lines = "\n".join(f"- `{net}`" for net in fidelity.nets) or "- （未识别到网络名）"
    component_lines = (
        "\n".join(f"- `{ref}`" for ref in fidelity.major_components)
        or "- （未识别到 IC 位号）"
    )
    summary_block = _page_summary_block(fidelity, raw_ocr_text)

    return f"""## 5. OCR 保真摘录（检索依据，禁止改写）

> 以下内容由 PDF 文本层原样提取，用于 RAG 检索与引证；若与上文 VLM 报告不一致，以本节为准。

### 5.1 模块分区标签
{module_lines}

### 5.2 网络名清单
{net_lines}

### 5.3 主要器件位号
{component_lines}
{summary_block}

### 5.4 OCR 全文
```text
{raw_ocr_text.strip()}
```
"""


def build_fidelity_page_markdown(
    layout: PageLayoutResult,
    *,
    project_id: str,
) -> str:
    """Build a page report from OCR only (no VLM narrative)."""
    fields = extract_fidelity_fields(layout.raw_ocr_text)
    module_lines = (
        "\n".join(f"- `{label}`" for label in fields.module_labels)
        or "- （未识别到模块分区标签）"
    )
    net_lines = "\n".join(f"- `{net}`" for net in fields.nets) or "- （未识别到网络名）"
    component_lines = (
        "\n".join(f"- `{ref}`" for ref in fields.major_components)
        or "- （未识别到 IC 位号）"
    )
    summary_block = _page_summary_block(fields, layout.raw_ocr_text)

    return f"""## 1. 模块图纸基本信息
* **图纸页码**: Page {layout.page}
* **项目代号**: {project_id}
* **提取方式**: OCR 保真（未经过 VLM 改写）

## 2. 模块分区标签（OCR 原样）
{module_lines}

## 3. 网络名清单（OCR 原样）
{net_lines}

## 4. 主要器件位号（OCR 原样）
{component_lines}
{summary_block}

{build_fidelity_appendix(page=layout.page, raw_ocr_text=layout.raw_ocr_text, fields=fields).strip()}
"""


def build_fidelity_extraction(
    layout: PageLayoutResult,
    *,
    project_id: str,
) -> PageExtraction:
    """Create a page extraction from OCR-only fidelity content."""
    fields = extract_fidelity_fields(layout.raw_ocr_text)
    return PageExtraction(
        page=layout.page,
        markdown=build_fidelity_page_markdown(layout, project_id=project_id),
        major_components=fields.major_components,
        nets=fields.nets,
        interfaces=fields.interfaces,
    )


_FIDELITY_APPENDIX_MARKER = "## 5. OCR 保真摘录（检索依据，禁止改写）"


def enrich_with_fidelity(
    extraction: PageExtraction,
    layout: PageLayoutResult,
) -> PageExtraction:
    """Append OCR fidelity data to a VLM-generated page extraction."""
    fields = extract_fidelity_fields(layout.raw_ocr_text)
    if _FIDELITY_APPENDIX_MARKER in extraction.markdown:
        return PageExtraction(
            page=extraction.page,
            markdown=extraction.markdown,
            major_components=_merge_unique(extraction.major_components, fields.major_components),
            nets=_merge_unique(extraction.nets, fields.nets),
            interfaces=_merge_unique(extraction.interfaces, fields.interfaces),
        )
    return PageExtraction(
        page=extraction.page,
        markdown=(
            extraction.markdown.rstrip()
            + "\n\n"
            + build_fidelity_appendix(
                page=layout.page,
                raw_ocr_text=layout.raw_ocr_text,
                fields=fields,
            )
        ),
        major_components=_merge_unique(extraction.major_components, fields.major_components),
        nets=_merge_unique(extraction.nets, fields.nets),
        interfaces=_merge_unique(extraction.interfaces, fields.interfaces),
    )
