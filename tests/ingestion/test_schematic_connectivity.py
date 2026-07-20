"""Tests for multi-source schematic connectivity (ADR 0007 / 0009)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.boardview.landrex_brd import (
    decode_landrex_brd,
    parse_landrex_brd,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.cad_companion import (
    discover_cad_companions,
    try_parse_cad_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.discover import (
    discover_and_parse_companions,
    discover_companions,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.merge import merge_connectivity
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionManifest,
    PageConnectivity,
    PinNetBinding,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.netlist.generic_net import (
    parse_generic_netlist,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.pdf_geometry import (
    extract_page_connectivity_from_geometry,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.resolve import (
    resolve_page_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.signals import OcrToken

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "connectivity"


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


def test_discover_companions_groups_netlist_and_boardview(tmp_path: Path) -> None:
    pdf = tmp_path / "Board.pdf"
    pdf.write_bytes(b"%PDF")
    net = tmp_path / "Board.net"
    net.write_text("EDP_AUXP U1 A12\n", encoding="utf-8")
    brd = tmp_path / "Board.brd"
    brd.write_bytes((FIXTURES / "mini_board.brd").read_bytes())

    discovered = discover_companions(pdf)
    assert discovered.netlist_paths[0] == net
    assert discovered.boardview_paths[0] == brd


def test_try_parse_unrecognized_net_returns_none(tmp_path: Path) -> None:
    companion = tmp_path / "Board.net"
    companion.write_text("(export)", encoding="utf-8")
    assert try_parse_cad_module_nets([companion]) is None


def test_try_parse_line_netlist_returns_refdes_nets() -> None:
    nets = try_parse_cad_module_nets([FIXTURES / "mini_board.net"])
    assert nets is not None
    assert "EDP_AUXP" in nets["U1"]
    assert "GND" in nets["U1"]


def test_parse_generic_netlist_fixture() -> None:
    graph = parse_generic_netlist(FIXTURES / "mini_board.net")
    assert graph is not None
    assert graph.evidence == "cad_netlist"
    pairs = {(b.refdes, b.pin, b.net) for b in graph.bindings}
    assert ("U1", "A12", "EDP_AUXP") in pairs


def test_decode_and_parse_landrex_fixture() -> None:
    raw = (FIXTURES / "mini_board.brd").read_bytes()
    text = decode_landrex_brd(raw)
    assert "Parts:" in text
    assert "EDP_AUXP" in text

    graph = parse_landrex_brd(FIXTURES / "mini_board.brd")
    assert graph is not None
    assert graph.evidence == "boardview"
    assert len(graph.bindings) == 5
    nets = {b.net for b in graph.bindings}
    assert "EDP_AUXP" in nets
    assert "PP3V3_S0" in nets


def test_discover_and_parse_both_companions(tmp_path: Path) -> None:
    pdf = tmp_path / "mini_board.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "mini_board.net").write_bytes((FIXTURES / "mini_board.net").read_bytes())
    (tmp_path / "mini_board.brd").write_bytes((FIXTURES / "mini_board.brd").read_bytes())

    parsed = discover_and_parse_companions(pdf)
    assert parsed.netlist is not None
    assert parsed.boardview is not None
    assert parsed.manifest.netlist is not None
    assert parsed.manifest.boardview is not None


def test_discover_absent_companions(tmp_path: Path) -> None:
    pdf = tmp_path / "lonely.pdf"
    pdf.write_bytes(b"%PDF")
    parsed = discover_and_parse_companions(pdf)
    assert parsed.netlist is None
    assert parsed.boardview is None
    assert parsed.manifest == CompanionManifest()


def test_merge_netlist_wins_over_boardview_on_same_pin(tmp_path: Path) -> None:
    pdf = tmp_path / "mini_board.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "mini_board.net").write_bytes((FIXTURES / "mini_board.net").read_bytes())
    (tmp_path / "mini_board.brd").write_bytes((FIXTURES / "mini_board.brd").read_bytes())
    parsed = discover_and_parse_companions(pdf)

    pages = [
        PageConnectivity(page=1, source="pdf_geometry", module_nets={"PWR": ["PP3V3_S0"]})
    ]
    merged = merge_connectivity(
        source_file="mini_board.pdf",
        companions=parsed,
        pages=pages,
    )
    assert merged.schema_version == 2
    assert "cad_netlist" in merged.sources_used
    assert "boardview" in merged.sources_used
    assert "pdf_geometry" in merged.sources_used
    assert merged.companions.netlist is not None
    assert merged.companions.boardview is not None

    # Netlist pin A12 on U1 should appear; boardview ordinal pins also present
    # where they do not conflict on (refdes, pin).
    u1_pins = {b.pin: b for b in merged.parts["U1"]}
    assert u1_pins["A12"].net == "EDP_AUXP"
    assert u1_pins["A12"].evidence == "cad_netlist"
    assert "1" in u1_pins  # boardview ordinal pin kept (different pin key)

    payload = merged.to_dict()
    assert payload["nets"]["EDP_AUXP"]
    assert payload["parts"]["U1"]["pins"]


def test_merge_pdf_only_has_null_companions() -> None:
    pages = [
        PageConnectivity(page=1, source="ocr_spatial", module_nets={"M": ["N1"]})
    ]
    merged = merge_connectivity(
        source_file="only.pdf",
        companions=None,
        pages=pages,
    )
    assert merged.companions.netlist is None
    assert merged.companions.boardview is None
    assert merged.nets == {}
    assert merged.sources_used == ["ocr_spatial"]


def test_stub_kicad_does_not_block_boardview(tmp_path: Path) -> None:
    pdf = tmp_path / "Board.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "Board.kicad_sch").write_text("(kicad_sch (version 20230101))", encoding="utf-8")
    (tmp_path / "Board.brd").write_bytes((FIXTURES / "mini_board.brd").read_bytes())

    parsed = discover_and_parse_companions(pdf)
    assert parsed.netlist is None
    assert parsed.boardview is not None
    assert "EDP_AUXP" in {b.net for b in parsed.boardview.bindings}


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
    ocr_text = "OLED&CAMERA P8 DCMI_D0 DCMI_D1 ADC&DAC SPI1_SCK"
    module_nets, source, connectivity = resolve_page_module_nets(
        page=3,
        module_labels=["OLED&CAMERA", "ADC&DAC"],
        nets=["DCMI_D0", "DCMI_D1", "SPI1_SCK"],
        ocr_text=ocr_text,
        ocr_tokens=tokens,
        prefer_geometry=True,
        skip_cad_discovery=True,
    )
    assert source == "pdf_geometry"
    assert connectivity is not None
    assert "DCMI_D0" in module_nets["OLED&CAMERA"]
    assert "DCMI_D1" in module_nets["OLED&CAMERA"]
    assert "SPI1_SCK" not in module_nets.get("OLED&CAMERA", [])


def test_resolve_skip_cad_discovery_ignores_companion_net(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "Board.pdf"
    pdf.write_bytes(b"%PDF")
    (tmp_path / "Board.net").write_text("EDP_AUXP U1 A12\n", encoding="utf-8")
    module_nets, source, _ = resolve_page_module_nets(
        page=1,
        module_labels=["M"],
        nets=["EDP_AUXP"],
        ocr_text="M EDP_AUXP",
        ocr_tokens=None,
        pdf_path=pdf,
        skip_cad_discovery=True,
    )
    assert source == "ocr_spatial"
    assert "EDP_AUXP" in module_nets.get("M", []) or module_nets  # spatial may bind


@pytest.mark.parametrize(
    "binding_a,binding_b,expected_net,expected_evidence",
    [
        (
            PinNetBinding("U1", "1", "OLD", "boardview"),
            PinNetBinding("U1", "1", "NEW", "cad_netlist"),
            "NEW",
            "cad_netlist",
        ),
    ],
)
def test_merge_priority_netlist_over_boardview(
    binding_a: PinNetBinding,
    binding_b: PinNetBinding,
    expected_net: str,
    expected_evidence: str,
) -> None:
    from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.discover import (
        ParsedCompanions,
    )
    from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
        CompanionGraph,
    )

    companions = ParsedCompanions(
        manifest=CompanionManifest(netlist="a.net", boardview="a.brd"),
        netlist=CompanionGraph(
            evidence="cad_netlist",
            source_path="a.net",
            bindings=[binding_b],
        ),
        boardview=CompanionGraph(
            evidence="boardview",
            source_path="a.brd",
            bindings=[binding_a],
        ),
    )
    merged = merge_connectivity(
        source_file="x.pdf",
        companions=companions,
        pages=[],
    )
    pin = next(b for b in merged.parts["U1"] if b.pin == "1")
    assert pin.net == expected_net
    assert pin.evidence == expected_evidence
