"""Parse vision-model responses from schematic PDF pages."""

from __future__ import annotations

import json
import re
from typing import Any

from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction

_META_COMMENT = re.compile(
    r"<!--\s*ee_wiki:major_components=([^;]*);nets=([^;]*);interfaces=([^>]*)\s*-->",
    re.IGNORECASE,
)
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_MARKDOWN_FIELD = re.compile(
    r'"markdown"\s*:\s*"((?:\\.|[^"\\])*)"',
    re.DOTALL,
)
_TRUNCATED_MARKDOWN_FIELD = re.compile(r'"markdown"\s*:\s*"(.*)', re.DOTALL)
_DESIGNATOR = re.compile(r"\b([UCRLDQXJFETSW]\d+[A-Z]?)\b", re.IGNORECASE)
_NET_IN_BACKTICKS = re.compile(r"`([A-Z][A-Z0-9_./+-]{1,48})`")
_PLACEHOLDER_HINTS = (
    "本页主要功能块",
    "本页核心主题",
    "中英文并列",
    "如「STM32F407",
    "按本页实际内容动态命名",
)
_REPETITION_WINDOW = 24


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _split_csv_field(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    fence = re.match(r"^```(?:markdown|md)?\s*\n(.*)\n```\s*$", stripped, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return stripped


def _decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return (
            value.replace("\\n", "\n")
            .replace("\\t", "\t")
            .replace('\\"', '"')
            .replace("\\\\", "\\")
        )


def _extract_json_payload(text: str) -> dict[str, Any]:
    stripped = _strip_code_fences(text.strip())
    candidates = [stripped]
    match = _JSON_BLOCK.search(stripped)
    if match:
        candidates.insert(0, match.group(1))

    for candidate in candidates:
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            field = _JSON_MARKDOWN_FIELD.search(candidate)
            if field:
                return {
                    "markdown": _decode_json_string(field.group(1)),
                    "major_components": [],
                    "nets": [],
                    "interfaces": [],
                }
            truncated = _TRUNCATED_MARKDOWN_FIELD.search(candidate)
            if truncated:
                raw = truncated.group(1)
                end = re.search(r'(?<!\\)"\s*,\s*"major_components"', raw)
                if end:
                    raw = raw[: end.start()]
                return {
                    "markdown": _decode_json_string(raw),
                    "major_components": [],
                    "nets": [],
                    "interfaces": [],
                }
    return {}


def _extract_meta_comment(text: str) -> tuple[str, list[str], list[str], list[str]]:
    match = _META_COMMENT.search(text)
    if not match:
        return text, [], [], []
    body = (text[: match.start()] + text[match.end() :]).strip()
    return (
        body,
        _split_csv_field(match.group(1)),
        _split_csv_field(match.group(2)),
        _split_csv_field(match.group(3)),
    )


def _infer_metadata_from_markdown(markdown: str) -> tuple[list[str], list[str], list[str]]:
    components = _DESIGNATOR.findall(markdown)
    nets = [net for net in _NET_IN_BACKTICKS.findall(markdown) if net.upper() not in {"MCU", "LDO"}]
    interfaces: list[str] = []
    for token in nets:
        upper = token.upper()
        if any(key in upper for key in ("I2C", "SPI", "USB", "UART", "CAN", "RMII", "MDIO", "SWD", "JTAG")):
            interfaces.append(token)
    return (
        _dedupe(components),
        _dedupe(nets),
        _dedupe(interfaces),
    )


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


def _truncate_repetition(text: str) -> str:
    """Cut runaway generation when the model repeats the same substring."""
    if len(text) < _REPETITION_WINDOW * 3:
        return text
    window = text[-_REPETITION_WINDOW:]
    first = text.find(window)
    if first == -1:
        return text
    second = text.find(window, first + _REPETITION_WINDOW)
    if second == -1:
        return text
    return text[:second].rstrip()


def _remove_placeholder_lines(markdown: str) -> str:
    lines: list[str] = []
    for line in markdown.splitlines():
        if any(hint in line for hint in _PLACEHOLDER_HINTS):
            continue
        if line.strip().startswith("{") and '"markdown"' in line:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _finalize_markdown(markdown: str) -> str:
    cleaned = _remove_placeholder_lines(_truncate_repetition(markdown.strip()))
    cleaned, _, _, _ = _extract_meta_comment(cleaned)
    return cleaned.strip()


def parse_page_response(text: str, *, page: int) -> PageExtraction:
    """Parse a vision model response into :class:`PageExtraction`.

    Accepts Markdown-first output (preferred) or legacy JSON payloads.
    """
    stripped = text.strip()
    payload = _extract_json_payload(stripped)

    if payload:
        markdown = _finalize_markdown(str(payload.get("markdown", "")).strip())
        components = _coerce_str_list(payload.get("major_components"))
        nets = _coerce_str_list(payload.get("nets"))
        interfaces = _coerce_str_list(payload.get("interfaces"))
    else:
        body = _strip_code_fences(stripped)
        body, meta_components, meta_nets, meta_interfaces = _extract_meta_comment(body)
        markdown = _finalize_markdown(body)
        inferred_components, inferred_nets, inferred_interfaces = _infer_metadata_from_markdown(
            markdown
        )
        components = meta_components or inferred_components
        nets = meta_nets or inferred_nets
        interfaces = meta_interfaces or inferred_interfaces

    if not markdown:
        markdown = _finalize_markdown(stripped)

    if payload and not components and not nets:
        inferred_components, inferred_nets, inferred_interfaces = _infer_metadata_from_markdown(
            markdown
        )
        components = inferred_components
        nets = inferred_nets
        interfaces = inferred_interfaces
    elif not payload and not components and not nets:
        inferred_components, inferred_nets, inferred_interfaces = _infer_metadata_from_markdown(
            markdown
        )
        components = components or inferred_components
        nets = nets or inferred_nets
        interfaces = interfaces or inferred_interfaces

    return PageExtraction(
        page=page,
        markdown=markdown,
        major_components=_dedupe(components),
        nets=_dedupe(nets),
        interfaces=_dedupe(interfaces),
    )


__all__ = ["parse_page_response"]
