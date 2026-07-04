"""Automatic keyword extraction for engineering documents.

Extracts structured keywords from document content during ingestion:
- Part numbers (IC designators like AMS1117, STM32F407VGT6)
- Voltage/current values (3.3V, 1.8V, 500mA)
- Communication protocols (I2C, SPI, UART, USB, PCIE)
- Package types (SOT-223, QFP-100, BGA-256)
- Connector/interface names (HDMI, DisplayPort, Ethernet)

These keywords power the metadata_keyword_boost in retrieval.
"""

from __future__ import annotations

import re

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


def extract_keywords(content: str) -> list[str]:
    """Extract engineering keywords from document content.

    Args:
        content: Full Markdown text of the processed document.

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

    for match in _PROTOCOL_RE.finditer(content):
        keywords.add(match.group(1).upper())

    for match in _PACKAGE_RE.finditer(content):
        keywords.add(match.group(1).upper().replace(" ", ""))

    keywords -= _NOISE_PARTS

    sorted_kw = sorted(keywords, key=lambda k: (-len(k), k))
    return sorted_kw[:_MAX_KEYWORDS]
