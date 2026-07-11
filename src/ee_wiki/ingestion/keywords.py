"""Automatic keyword extraction for engineering documents.

Extracts structured keywords from document content during ingestion:
- Part numbers (IC designators like AMS1117, STM32F407VGT6)
- Voltage/current values (3.3V, 1.8V, 500mA)
- Communication protocols (I2C, SPI, UART, USB, PCIE)
- Package types (SOT-223, QFP-100, BGA-256)
- Connector/interface names (HDMI, DisplayPort, Ethernet)
- Failure-analysis terms (failure modes, symptoms, batch/lot IDs)

These keywords power the metadata_keyword_boost in retrieval.
"""

from __future__ import annotations

import re

from ee_wiki.common.serialization import FAILURE_ANALYSIS_DOCUMENT_TYPE

_PART_NUMBER_RE = re.compile(
    r"\b("
    r"[A-Z]{2,}[0-9]{2,}[A-Z0-9\-/]*"  # AMS1117, TPS62840, STM32F407VGT6
    r"|[A-Z][0-9]+[A-Z][0-9A-Z\-]*"  # U0902, R101, C205
    r"|[A-Z]{1,3}[0-9]{4,}[A-Z0-9\-]*"  # AT24C02, W25Q128
    r")\b",
    re.ASCII,
)

_VOLTAGE_RE = re.compile(
    r"\b(\d+\.?\d*)\s*(V|mV|kV)\b",
    re.IGNORECASE,
)

_CURRENT_RE = re.compile(
    r"\b(\d+\.?\d*)\s*(A|mA|µA|uA|nA)\b",
    re.IGNORECASE,
)

_PROTOCOLS = frozenset({
    "I2C", "SPI", "UART", "USART", "USB", "CAN", "LIN",
    "PCIE", "HDMI", "LVDS", "MIPI", "JTAG", "SWD",
    "DDR", "DDR2", "DDR3", "DDR4", "DDR5", "LPDDR4", "LPDDR5",
    "SDIO", "EMMC", "QSPI", "I2S", "TDM", "PWM", "ADC", "DAC",
    "ETHERNET", "RGMII", "SGMII", "MDIO",
    "RS232", "RS485", "RS422",
    "DISPLAYPORT", "DP", "DVI", "VGA",
    "GPIO", "SDRAM",
})

_PROTOCOL_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in sorted(_PROTOCOLS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

_PACKAGE_RE = re.compile(
    r"\b("
    r"SOT[\-]?\d{2,3}[A-Z]*"
    r"|QFP[\-]?\d+"
    r"|LQFP[\-]?\d+"
    r"|TQFP[\-]?\d+"
    r"|BGA[\-]?\d+"
    r"|QFN[\-]?\d+"
    r"|DFN[\-]?\d+"
    r"|SOIC[\-]?\d+"
    r"|SOP[\-]?\d+"
    r"|TSOP[\-]?\d+"
    r"|MSOP[\-]?\d+"
    r"|TSSOP[\-]?\d+"
    r"|SSOP[\-]?\d+"
    r"|DIP[\-]?\d+"
    r"|PDIP[\-]?\d+"
    r"|TO[\-]?\d+"
    r"|WLCSP[\-]?\d+"
    r"|CSP[\-]?\d+"
    r"|LGA[\-]?\d+"
    r")\b",
    re.IGNORECASE,
)

_NOISE_PARTS = frozenset({
    "DC", "AC", "IC", "IF", "IO", "ID", "IN", "IT", "IS", "ON", "OR",
    "OF", "AN", "AS", "AT", "NO", "TO", "UP", "SO", "DO", "GO",
    "MIN", "MAX", "TYP", "NOTE", "REF", "PIN", "VCC", "VDD", "VSS",
    "GND", "OUT", "CLK", "EN", "RST",
})

_MIN_PART_LEN = 4
_MAX_KEYWORDS = 50

_DESIGNATOR_RE = re.compile(r"^[URCLQD]\d{1,5}[A-Z]?$", re.ASCII)

_FAILURE_MODES = frozenset({
    "SHORT_CIRCUIT", "OPEN_CIRCUIT", "ESD", "EOS", "LATCHUP", "LATCH_UP", "BURNOUT", "BURN_OUT",
    "THERMAL_RUNAWAY", "OVERVOLTAGE", "OVER_VOLTAGE", "UNDERVOLTAGE", "UNDER_VOLTAGE",
    "OVERCURRENT", "OVER_CURRENT",
    "SOLDER_JOINT", "TOMBSTONE", "BRIDGE", "SOLDER_BRIDGE", "VOID", "CRACK",
    "CORROSION", "CONTAMINATION", "MICROCRACK", "MICRO_CRACK", "DELAMINATION",
    "WHISKER", "CREEP", "FATIGUE", "FRACTURE",
})

_SYMPTOM_TERMS = frozenset({
    "NO_BOOT", "NO_POWER", "INTERMITTENT", "OVERHEATING", "RESET",
    "HANG", "CRASH", "GLITCH", "NO_DISPLAY", "ARTIFACT",
    "DATA_CORRUPTION", "LINK_DOWN", "TIMEOUT", "BROWNOUT",
    "HARD_FAULT", "WATCHDOG", "FAIL_SAFE", "FALSE_TRIGGER",
})

_FAILURE_MODE_RE = re.compile(
    r"\b("
    r"short[\s\-]?circuit|open[\s\-]?circuit|esd|eos|latch[\s\-]?up|"
    r"thermal[\s\-]?runaway|over[\s\-]?voltage|under[\s\-]?voltage|"
    r"over[\s\-]?current|solder[\s\-]?joint|tombstone|solder[\s\-]?bridge|"
    r"void|micro[\s\-]?crack|delamination|whisker|creep|fatigue|fracture|"
    r"burn[\s\-]?out|contamination|corrosion"
    r")\b",
    re.IGNORECASE,
)

_SYMPTOM_RE = re.compile(
    r"\b("
    r"no[\s\-]?boot|no[\s\-]?power|intermittent|over[\s\-]?heat(?:ing)?|"
    r"reset|hang|crash|glitch|no[\s\-]?display|artifact|"
    r"data[\s\-]?corruption|link[\s\-]?down|timeout|brown[\s\-]?out|"
    r"hard[\s\-]?fault|watchdog|fail[\s\-]?safe|false[\s\-]?trigger"
    r")\b",
    re.IGNORECASE,
)

_BATCH_LOT_RE = re.compile(
    r"\bbatch\s+lot\s+([A-Z0-9][A-Z0-9\-_/]{2,})\b"
    r"|\b(?:LOT|BATCH|lot|batch)[\s\-#:]+([A-Z0-9][A-Z0-9\-_/]{3,})\b",
    re.ASCII,
)

_DATE_CODE_RE = re.compile(
    r"\b(?:DATE[\s\-]?CODE|date[\s\-]?code|DC)[\s\-#:]*([0-9]{4,6}[A-Z]?)\b",
    re.IGNORECASE,
)

_RMA_RE = re.compile(
    r"\b(RMA|NCR|CAR)[\s\-#:]*([A-Z0-9][A-Z0-9\-_/]{2,})\b",
    re.ASCII,
)


def _normalize_fa_token(raw: str) -> str:
    """Normalize a failure-analysis phrase to an uppercase underscore token."""
    cleaned = re.sub(r"[\s\-]+", "_", raw.strip().upper())
    return cleaned.strip("_")


def _extract_fa_keywords(content: str) -> set[str]:
    """Extract failure-analysis keywords from document content."""
    keywords: set[str] = set()

    for match in _FAILURE_MODE_RE.finditer(content):
        token = _normalize_fa_token(match.group(1))
        if token in _FAILURE_MODES:
            keywords.add(token)

    for match in _SYMPTOM_RE.finditer(content):
        token = _normalize_fa_token(match.group(1))
        if token in _SYMPTOM_TERMS:
            keywords.add(token)

    for match in _BATCH_LOT_RE.finditer(content):
        lot_id = match.group(1) or match.group(2)
        if lot_id:
            keywords.add(f"LOT:{lot_id.upper()}")

    for match in _DATE_CODE_RE.finditer(content):
        keywords.add(f"DATECODE:{match.group(1).upper()}")

    for match in _RMA_RE.finditer(content):
        keywords.add(f"{match.group(1).upper()}:{match.group(2).upper()}")

    return keywords


def is_designator(token: str) -> bool:
    """Return whether ``token`` looks like a schematic reference designator."""
    cleaned = token.strip()
    if not cleaned:
        return False
    return bool(_DESIGNATOR_RE.match(cleaned))


def is_part_number_keyword(token: str) -> bool:
    """Return whether ``token`` looks like an IC/part number (not a designator)."""
    cleaned = token.strip()
    if len(cleaned) < _MIN_PART_LEN or cleaned in _NOISE_PARTS:
        return False
    if is_designator(cleaned):
        return False
    return bool(_PART_NUMBER_RE.fullmatch(cleaned))


def extract_protocol_names(content: str) -> list[str]:
    """Return deduplicated protocol/interface names found in content.

    Args:
        content: Document Markdown text.

    Returns:
        Sorted list of uppercase protocol tokens (e.g. ``I2C``, ``SPI``).
    """
    if not content:
        return []
    names = {match.group(1).upper() for match in _PROTOCOL_RE.finditer(content)}
    return sorted(names)


def extract_package_tokens(content: str) -> list[str]:
    """Return package designators found in content.

    Args:
        content: Document Markdown text.

    Returns:
        Sorted list of normalized package strings (e.g. ``LQFP144``, ``SOT-223``).
    """
    if not content:
        return []
    packages = {
        match.group(1).upper().replace(" ", "")
        for match in _PACKAGE_RE.finditer(content)
    }
    return sorted(packages)


def extract_keywords(
    content: str,
    *,
    document_type: str | None = None,
) -> list[str]:
    """Extract engineering keywords from document content.

    Args:
        content: Full Markdown text of the processed document.
        document_type: Optional document type for type-specific rules
            (e.g. ``failure_analysis``).

    Returns:
        Deduplicated, sorted list of keywords (max 50).
    """
    if not content:
        return []

    keywords: set[str] = set()

    for match in _PART_NUMBER_RE.finditer(content):
        part = match.group(1)
        if len(part) >= _MIN_PART_LEN and part not in _NOISE_PARTS:
            keywords.add(part)

    for match in _VOLTAGE_RE.finditer(content):
        value, unit = match.group(1), match.group(2)
        keywords.add(f"{value}{unit.upper()}")

    for match in _CURRENT_RE.finditer(content):
        value, unit = match.group(1), match.group(2)
        normalized_unit = unit.replace("µ", "u")
        keywords.add(f"{value}{normalized_unit}")

    keywords.update(extract_protocol_names(content))
    keywords.update(extract_package_tokens(content))

    if document_type == FAILURE_ANALYSIS_DOCUMENT_TYPE:
        keywords.update(_extract_fa_keywords(content))

    keywords -= _NOISE_PARTS

    sorted_kw = sorted(keywords, key=lambda k: (-len(k), k))
    return sorted_kw[:_MAX_KEYWORDS]
