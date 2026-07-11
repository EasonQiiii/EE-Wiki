"""Extract structured datasheet metadata from VLM/OCR Markdown."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ee_wiki.ingestion.keywords import extract_package_tokens, extract_protocol_names

_PIN_COUNT_RE = re.compile(
    r"\b(\d{1,4})[\s\-]?pins?\b",
    re.IGNORECASE,
)

_PACKAGE_PIN_RE = re.compile(
    r"\b(?:"
    r"LQFP|TQFP|QFP|QFN|DFN|BGA|WLCSP|CSP|LGA|SOIC|SOP|TSSOP|MSOP|SSOP|DIP|PDIP"
    r")[\s\-]?(\d{1,4})\b",
    re.IGNORECASE,
)

_SUPPLY_RANGE_RE = re.compile(
    r"\b(\d+\.?\d*)\s*V\s*(?:to|–|-|—)\s*(\d+\.?\d*)\s*V\b",
    re.IGNORECASE,
)

_SUPPLY_CONTEXT_RE = re.compile(
    r"(?:VDD|VCC|supply|operating|input)\s+(?:voltage\s+)?(?:range\s+)?"
    r"(?:of\s+)?(\d+\.?\d*)\s*V(?:\s*(?:to|–|-|—)\s*(\d+\.?\d*)\s*V)?",
    re.IGNORECASE,
)

_VOLTAGE_RE = re.compile(
    r"\b(\d+\.?\d*)\s*V\b",
    re.IGNORECASE,
)

_MAX_SUPPLY_VOLTAGES = 10
_MIN_SUPPLY_V = 0.5
_MAX_SUPPLY_V = 60.0


@dataclass(frozen=True)
class DatasheetFields:
    """Structured electrical metadata extracted from datasheet content."""

    supply_voltage: list[str] = field(default_factory=list)
    pin_count: int | None = None
    package: str | None = None
    interfaces: list[str] = field(default_factory=list)


def _format_voltage(value: str) -> str:
    """Normalize a numeric voltage string to ``X.YV`` form."""
    numeric = float(value)
    if numeric.is_integer():
        return f"{int(numeric)}V"
    return f"{numeric}V"


def _extract_supply_voltages(content: str) -> list[str]:
    """Extract supply voltage strings from datasheet Markdown."""
    found: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        if value not in seen:
            seen.add(value)
            found.append(value)

    for low, high in _SUPPLY_RANGE_RE.findall(content):
        add(f"{_format_voltage(low)}-{_format_voltage(high)}")

    for match in _SUPPLY_CONTEXT_RE.finditer(content):
        low = match.group(1)
        high = match.group(2)
        if high:
            add(f"{_format_voltage(low)}-{_format_voltage(high)}")
        else:
            add(_format_voltage(low))

    if len(found) < _MAX_SUPPLY_VOLTAGES:
        for match in _VOLTAGE_RE.finditer(content):
            value = float(match.group(1))
            if _MIN_SUPPLY_V <= value <= _MAX_SUPPLY_V:
                add(_format_voltage(match.group(1)))
            if len(found) >= _MAX_SUPPLY_VOLTAGES:
                break

    return found[:_MAX_SUPPLY_VOLTAGES]


def _extract_pin_count(content: str) -> int | None:
    """Extract pin count from explicit counts and package designators."""
    candidates: list[int] = []
    for match in _PIN_COUNT_RE.finditer(content):
        candidates.append(int(match.group(1)))
    for match in _PACKAGE_PIN_RE.finditer(content):
        candidates.append(int(match.group(1)))
    if not candidates:
        return None
    return max(candidates)


def _extract_package(content: str) -> str | None:
    """Return the longest package token found in content."""
    packages = extract_package_tokens(content)
    if not packages:
        return None
    return max(packages, key=len)


def extract_datasheet_fields(content: str) -> DatasheetFields:
    """Extract structured datasheet metadata from merged Markdown content.

    Args:
        content: Full datasheet Markdown from VLM/OCR merge.

    Returns:
        Parsed supply voltages, pin count, package, and interface names.
    """
    if not content.strip():
        return DatasheetFields()

    return DatasheetFields(
        supply_voltage=_extract_supply_voltages(content),
        pin_count=_extract_pin_count(content),
        package=_extract_package(content),
        interfaces=extract_protocol_names(content),
    )
