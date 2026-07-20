"""Lossless OCR extraction for schematic PDF pages."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.ingestion.parsers.schematic_pdf.layout import PageLayoutResult
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction
from ee_wiki.ingestion.parsers.schematic_pdf.signals import (
    OcrToken,
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
_MODULE_LABEL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9 &/+-]{2,48}$")
_DESIGNATOR_TOKEN_PATTERN = re.compile(r"^(?:PI|CO|PA|NL)[A-Z0-9]+$", re.IGNORECASE)
_PINLIKE_SLASH_PART = re.compile(
    r"^(?:CD|WP|NC|IO|I|O|D|DATA\d*|[A-Z]{0,3}\d+[A-Z0-9]*)$",
    re.IGNORECASE,
)
# Protocol-ish tokens allowed to contain digits in zone titles (USB/CAN, RS232/RS485).
_PROTOCOLISH_TOKEN = re.compile(
    r"^(?:RS|USB|CAN|SPI|I2C|I2S|UART|USART|SDIO|ADC|DAC|PWM|ETH|HDMI|MIPI|BT|GPS|NFC)\d*$",
    re.IGNORECASE,
)
# MCU pin alternate-function / debug tokens mistaken for zone titles (TMS/SWDIO, WR/CLK).
_PIN_ALT_TOKENS = frozenset(
    {
        "TMS",
        "TCK",
        "TDO",
        "TDI",
        "TRST",
        "SWDIO",
        "SWCLK",
        "SWO",
        "CLK",
        "WR",
        "RD",
        "BOOT",
        "BOOT0",
        "BOOT1",
        "CLKIN",
        "XTAL",
        "OSC",
    }
)
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
        "NRST",
        "VDD",
        "VSS",
    }
)
# Single-token zone titles that appear as standalone OCR lines on schematics.
# Kept as a closed generic set to avoid treating pin names (SCL, SCK, …) as zones.
_GENERIC_SINGLE_WORD_ZONES = frozenset(
    {
        "WIRELESS",
        "FLASH",
        "EEPROM",
        "REMOTE",
        "AUDIO",
        "POWER",
        "ETHERNET",
        "CAMERA",
        "DISPLAY",
        "SENSOR",
        "BATTERY",
        "CHARGER",
        "MOTOR",
        "DEBUG",
        "CONNECTOR",
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


def _is_designator_cluster(candidate: str) -> bool:
    """Return True for glued pin/refdes OCR noise such as ``PIC7501 PIC7502``."""
    tokens = [token for token in candidate.split() if token]
    return bool(tokens) and all(_DESIGNATOR_TOKEN_PATTERN.fullmatch(token) for token in tokens)


def _slash_side_token(part: str) -> str:
    """Return the primary token of a slash-label side (ignore trailing ``&…``)."""
    return part.split("&", 1)[0].strip().upper()


def _looks_like_pin_mux_token(token: str) -> bool:
    """Return True for MCU pin / alt-function tokens (not interface zone names)."""
    upper = token.upper()
    if not upper:
        return True
    if upper in _PIN_ALT_TOKENS:
        return True
    if upper.startswith(("GPIO", "MODE", "PHYAD", "REGOFF", "SWD")):
        return True
    # Numbered pad / pin names: PB2, LED1, RXD0, XTAL1 — but not RS232 / SPI1 / USB.
    if re.fullmatch(r"[A-Z]{1,4}\d+[A-Z0-9]*", upper):
        return not bool(_PROTOCOLISH_TOKEN.fullmatch(upper))
    return False


def _is_pinlike_slash_label(candidate: str) -> bool:
    """Return True for pin/mux labels like ``CD/DATA3`` or ``TMS/SWDIO``.

    Keeps real zone titles such as ``USB/CAN`` and ``RS232/RS485``.
    """
    if "/" not in candidate:
        return False
    parts = [part for part in candidate.split("/") if part.strip()]
    if len(parts) < 2:
        return False
    sides = [_slash_side_token(part) for part in parts]
    if any(_looks_like_pin_mux_token(side) for side in sides):
        return True
    # Connector pin stubs: CD/DATA3, WP/NC — not protocol zone titles like RS232/RS485.
    if all(_PINLIKE_SLASH_PART.fullmatch(side) for side in sides):
        if not all(_PROTOCOLISH_TOKEN.fullmatch(side) for side in sides):
            return True
    return False


def _is_module_zone_label(candidate: str) -> bool:
    """Keep schematic zone titles using structural rules only."""
    if _is_designator_cluster(candidate):
        return False
    if "&" in candidate and "/" not in candidate:
        return True
    if "/" in candidate:
        return not _is_pinlike_slash_label(candidate)
    # Multi-word titles: "ATK MODULE", "SD CARD", "6 AXIS SENSOR".
    if " " in candidate and len(candidate) >= 7:
        return True
    # Closed set of common single-word zone titles (not pin abbreviations).
    if candidate in _GENERIC_SINGLE_WORD_ZONES:
        return True
    return False


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


def _page_summary_block(
    fields: FidelityFields,
    raw_ocr_text: str,
    *,
    ocr_tokens: Sequence[OcrToken] | None = None,
    page: int = 1,
    source_pdf: Path | None = None,
    connectivity_enabled: bool = True,
    max_connector_distance: float = 90.0,
    cad_extensions: tuple[str, ...] | None = None,
) -> str:
    from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.resolve import (
        resolve_page_module_nets,
    )

    if connectivity_enabled:
        # Document-level netlist/boardview merge into sidecar (ADR 0009);
        # page Markdown stays PDF geometry / OCR spatial only.
        module_nets_map, evidence, _connectivity = resolve_page_module_nets(
            page=page,
            module_labels=fields.module_labels,
            nets=fields.nets,
            ocr_text=raw_ocr_text,
            ocr_tokens=ocr_tokens,
            pdf_path=source_pdf,
            cad_extensions=cad_extensions,
            max_connector_distance=max_connector_distance,
            skip_cad_discovery=True,
        )
    else:
        module_nets_map, evidence = None, None
    summary = build_page_signal_summary(
        fields.module_labels,
        fields.nets,
        ocr_text=raw_ocr_text,
        ocr_tokens=ocr_tokens,
        heading_level=3,
        module_nets_map=module_nets_map,
        evidence=evidence,
    )
    return f"\n\n{summary}" if summary else ""


def build_fidelity_appendix(
    *,
    page: int,
    raw_ocr_text: str,
    fields: FidelityFields | None = None,
    ocr_tokens: Sequence[OcrToken] | None = None,
    source_pdf: Path | None = None,
    connectivity_enabled: bool = True,
    max_connector_distance: float = 90.0,
    cad_extensions: tuple[str, ...] | None = None,
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
    summary_block = _page_summary_block(
        fidelity,
        raw_ocr_text,
        ocr_tokens=ocr_tokens,
        page=page,
        source_pdf=source_pdf,
        connectivity_enabled=connectivity_enabled,
        max_connector_distance=max_connector_distance,
        cad_extensions=cad_extensions,
    )

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
    connectivity_enabled: bool = True,
    max_connector_distance: float = 90.0,
    cad_extensions: tuple[str, ...] | None = None,
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
    summary_block = _page_summary_block(
        fields,
        layout.raw_ocr_text,
        ocr_tokens=layout.ocr_tokens or None,
        page=layout.page,
        source_pdf=layout.source_pdf,
        connectivity_enabled=connectivity_enabled,
        max_connector_distance=max_connector_distance,
        cad_extensions=cad_extensions,
    )

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

{build_fidelity_appendix(
    page=layout.page,
    raw_ocr_text=layout.raw_ocr_text,
    fields=fields,
    ocr_tokens=layout.ocr_tokens or None,
    source_pdf=layout.source_pdf,
    connectivity_enabled=connectivity_enabled,
    max_connector_distance=max_connector_distance,
    cad_extensions=cad_extensions,
).strip()}
"""


def build_fidelity_extraction(
    layout: PageLayoutResult,
    *,
    project_id: str,
    connectivity_enabled: bool = True,
    max_connector_distance: float = 90.0,
    cad_extensions: tuple[str, ...] | None = None,
) -> PageExtraction:
    """Create a page extraction from OCR-only fidelity content."""
    fields = extract_fidelity_fields(layout.raw_ocr_text)
    return PageExtraction(
        page=layout.page,
        markdown=build_fidelity_page_markdown(
            layout,
            project_id=project_id,
            connectivity_enabled=connectivity_enabled,
            max_connector_distance=max_connector_distance,
            cad_extensions=cad_extensions,
        ),
        major_components=fields.major_components,
        nets=fields.nets,
        interfaces=fields.interfaces,
    )


_FIDELITY_APPENDIX_MARKER = "## 5. OCR 保真摘录（检索依据，禁止改写）"


def enrich_with_fidelity(
    extraction: PageExtraction,
    layout: PageLayoutResult,
    *,
    connectivity_enabled: bool = True,
    max_connector_distance: float = 90.0,
    cad_extensions: tuple[str, ...] | None = None,
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
                ocr_tokens=layout.ocr_tokens or None,
                source_pdf=layout.source_pdf,
                connectivity_enabled=connectivity_enabled,
                max_connector_distance=max_connector_distance,
                cad_extensions=cad_extensions,
            )
        ),
        major_components=_merge_unique(extraction.major_components, fields.major_components),
        nets=_merge_unique(extraction.nets, fields.nets),
        interfaces=_merge_unique(extraction.interfaces, fields.interfaces),
    )
