"""Tests for datasheet structured field extraction."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.datasheet_pdf.fields import extract_datasheet_fields


def test_extracts_supply_voltage_range() -> None:
    content = "Operating voltage range: 2.0 V to 3.6 V over temperature."
    fields = extract_datasheet_fields(content)
    assert "2V-3.6V" in fields.supply_voltage


def test_extracts_named_supply_voltages() -> None:
    content = "Fixed outputs: 1.8V, 2.5V, and 3.3V. VDD supply 3.3V typical."
    fields = extract_datasheet_fields(content)
    assert "3.3V" in fields.supply_voltage
    assert "1.8V" in fields.supply_voltage


def test_extracts_pin_count_from_package_and_text() -> None:
    content = "Available in LQFP144 and 144-pin QFP packages."
    fields = extract_datasheet_fields(content)
    assert fields.pin_count == 144


def test_extracts_package_designator() -> None:
    content = "Package options include QFN-48 and LQFP100."
    fields = extract_datasheet_fields(content)
    assert fields.package == "LQFP100"


def test_extracts_interface_protocols() -> None:
    content = "Supports I2C, SPI, and RMII Ethernet interface."
    fields = extract_datasheet_fields(content)
    assert "I2C" in fields.interfaces
    assert "SPI" in fields.interfaces


def test_empty_content_returns_defaults() -> None:
    fields = extract_datasheet_fields("")
    assert fields.supply_voltage == []
    assert fields.pin_count is None
    assert fields.package is None
    assert fields.interfaces == []
