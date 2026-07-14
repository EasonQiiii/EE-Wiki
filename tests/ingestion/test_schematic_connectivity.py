"""Tests for CAD discovery and PDF geometry module↔net binding (ADR 0007)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.cad_companion import (
    discover_cad_companions,
    try_parse_cad_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.pdf_geometry import (
    extract_page_connectivity_from_geometry,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.resolve import (
    resolve_page_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.signals import OcrToken


def test_discover_cad_companions_prefers_same_stem(tmp_path: Path) -> None:
    pdf = tmp_path / "Board.pdf"
    pdf.write_bytes(b"%PDF")
    same_stem = tmp_path / "Board.net"
    same_stem.write_text("(export (version 1))", encoding="utf-8")
    other = tmp_path / "Other.kicad_sch"
    other.write_text("(kicad_sch)", encoding="utf-8")
    cad_dir = tmp_path / "cad"
    cad_dir.mkdir()
    sibling = cad_dir / "Board.SchDoc"
    sibling.write_text("altium", encoding="utf-8")

    found = discover_cad_companions(pdf)
    assert found[0] == same_stem
    assert other in found
    assert sibling in found


def test_try_parse_cad_module_nets_returns_none_until_parser_exists(
    tmp_path: Path,
) -> None:
    companion = tmp_path / "Board.net"
    companion.write_text("(export)", encoding="utf-8")
    assert try_parse_cad_module_nets([companion]) is None


def test_pdf_geometry_binds_connector_nets_to_nearest_module() -> None:
    """P8 near OLED&CAMERA should own DCMI nets; P11 near USB/CAN owns CAN."""
    tokens = (
        OcrToken("OLED&CAMERA", 100, 20, 220, 35),
        OcrToken("P8", 140, 80, 160, 95),
        OcrToken("DCMI_D0", 130, 110, 190, 125),
        OcrToken("DCMI_D1", 130, 130, 190, 145),
        OcrToken("DCMI_HSYNC", 130, 150, 210, 165),
        OcrToken("USB/CAN", 400, 20, 480, 35),
        OcrToken("P11", 430, 80, 455, 95),
        OcrToken("CAN_H", 420, 120, 470, 135),
        OcrToken("CAN_L", 420, 140, 470, 155),
    )
    modules = ["OLED&CAMERA", "USB/CAN"]
    nets = ["DCMI_D0", "DCMI_D1", "DCMI_HSYNC", "CAN_H", "CAN_L"]

    page = extract_page_connectivity_from_geometry(
        page=3,
        module_labels=modules,
        nets=nets,
        ocr_tokens=tokens,
        max_connector_distance=90.0,
    )
    assert page is not None
    assert page.source == "pdf_geometry"
    assert "DCMI_D0" in page.module_nets["OLED&CAMERA"]
    assert "DCMI_HSYNC" in page.module_nets["OLED&CAMERA"]
    assert "CAN_H" not in page.module_nets.get("OLED&CAMERA", [])
    assert "CAN_H" in page.module_nets["USB/CAN"]
    refs = {binding.refdes: binding for binding in page.connectors}
    assert refs["P8"].module == "OLED&CAMERA"
    assert refs["P11"].module == "USB/CAN"


def test_resolve_prefers_geometry_over_spatial_for_oled_pins() -> None:
    """Geometry should keep DCMI with OLED even if reading-order would attach SPI."""
    tokens = (
        OcrToken("OLED&CAMERA", 100, 20, 220, 35),
        OcrToken("P8", 140, 80, 160, 95),
        OcrToken("DCMI_D0", 130, 110, 190, 125),
        OcrToken("DCMI_D1", 130, 130, 190, 145),
        OcrToken("ADC&DAC", 100, 300, 180, 315),
        OcrToken("SPI1_SCK", 120, 340, 180, 355),
    )
    # Reading order groups SPI near OLED incorrectly in text-only windows;
    # spatial title cluster can also mis-bind. Geometry uses P8.
    ocr_text = "OLED&CAMERA P8 DCMI_D0 DCMI_D1 ADC&DAC SPI1_SCK"
    module_nets, source, connectivity = resolve_page_module_nets(
        page=3,
        module_labels=["OLED&CAMERA", "ADC&DAC"],
        nets=["DCMI_D0", "DCMI_D1", "SPI1_SCK"],
        ocr_text=ocr_text,
        ocr_tokens=tokens,
        prefer_geometry=True,
    )
    assert source == "pdf_geometry"
    assert connectivity is not None
    assert "DCMI_D0" in module_nets["OLED&CAMERA"]
    assert "DCMI_D1" in module_nets["OLED&CAMERA"]
    assert "SPI1_SCK" not in module_nets.get("OLED&CAMERA", [])
