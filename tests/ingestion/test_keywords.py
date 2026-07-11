"""Tests for automatic keyword extraction."""

from __future__ import annotations

from ee_wiki.ingestion.keywords import extract_keywords


def test_extracts_part_numbers() -> None:
    content = "The AMS1117 is a 1A low dropout regulator. See also TPS62840."
    keywords = extract_keywords(content)
    assert "AMS1117" in keywords
    assert "TPS62840" in keywords


def test_extracts_voltages() -> None:
    content = "Output voltage: 3.3V, input up to 15V. Dropout at 1.2V."
    keywords = extract_keywords(content)
    assert "3.3V" in keywords
    assert "15V" in keywords
    assert "1.2V" in keywords


def test_extracts_currents() -> None:
    content = "Max output current 1A. Quiescent current 5mA typical."
    keywords = extract_keywords(content)
    assert "1A" in keywords
    assert "5mA" in keywords


def test_extracts_protocols() -> None:
    content = "Supports I2C and SPI interfaces. Also has UART debug port."
    keywords = extract_keywords(content)
    assert "I2C" in keywords
    assert "SPI" in keywords
    assert "UART" in keywords


def test_extracts_packages() -> None:
    content = "Available in SOT-223 and SOT-89 packages."
    keywords = extract_keywords(content)
    assert "SOT-223" in keywords or "SOT223" in keywords
    assert "SOT-89" in keywords or "SOT89" in keywords


def test_filters_noise_words() -> None:
    content = "DC input voltage MIN 4.5V MAX 28V. Note: IC must be..."
    keywords = extract_keywords(content)
    assert "DC" not in keywords
    assert "MIN" not in keywords
    assert "MAX" not in keywords
    assert "4.5V" in keywords
    assert "28V" in keywords


def test_empty_content() -> None:
    assert extract_keywords("") == []


def test_max_keywords_cap() -> None:
    parts = " ".join(f"PART{i:04d}X" for i in range(100))
    keywords = extract_keywords(parts)
    assert len(keywords) <= 50


def test_deduplicates() -> None:
    content = "AMS1117 provides 3.3V. The AMS1117 is reliable at 3.3V."
    keywords = extract_keywords(content)
    assert keywords.count("AMS1117") == 1
    assert keywords.count("3.3V") == 1


def test_real_datasheet_content() -> None:
    """Simulate content from the AMS1117 datasheet."""
    content = """
    AMS1117 series adjustable and fixed voltage regulators.
    Available in SOT-223 and TO-252 packages.
    Output voltage: 1.5V, 1.8V, 2.5V, 2.85V, 3.3V, 5.0V.
    Maximum output current: 1A.
    Dropout voltage: 1.3V at 1A.
    Line regulation: 0.2% max.
    Load regulation: 0.4% max.
    Temperature range: -40 to 125 degrees.
    """
    keywords = extract_keywords(content)
    assert "AMS1117" in keywords
    assert "3.3V" in keywords
    assert "1.8V" in keywords
    assert "1A" in keywords
    has_sot = any("SOT" in k for k in keywords)
    assert has_sot


def test_extracts_failure_analysis_keywords() -> None:
    content = """
    RMA RMA-2024-001 for batch LOT B2024-117.
    Symptom: no boot after thermal runaway during over-voltage event.
    Failure mode: ESD damage on input. Date code DC 2445.
    """
    keywords = extract_keywords(content, document_type="failure_analysis")
    assert "LOT:B2024-117" in keywords
    assert "RMA:RMA-2024-001" in keywords
    assert "ESD" in keywords
    assert "THERMAL_RUNAWAY" in keywords
    assert "OVER_VOLTAGE" in keywords
    assert "NO_BOOT" in keywords
    assert "DATECODE:2445" in keywords


def test_fa_keywords_skipped_for_other_document_types() -> None:
    content = "LOT ABC123 no boot thermal runaway"
    keywords = extract_keywords(content, document_type="sop")
    assert not any(k.startswith("LOT:") for k in keywords)
    assert "NO_BOOT" not in keywords
