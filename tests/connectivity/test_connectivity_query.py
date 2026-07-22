"""Tests for schematic connectivity sidecar queries (ADR 0009)."""

from __future__ import annotations

import json
from pathlib import Path

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.connectivity.query import ConnectivityQuery, open_connectivity_query
from ee_wiki.connectivity.store import load_connectivity_documents
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionManifest,
    ConnectorBinding,
    PageConnectivity,
    PinNetBinding,
    SchematicConnectivity,
)


def _layout(processed: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={
            "sch": "schematic",
            "note": "engineering_note",
            "datasheet": "datasheet",
            "sop": "sop",
            "fa": "failure_analysis",
        },
        raw_dir=processed.parent / "raw",
        processed_dir=processed,
    )


def _write_sidecar(path: Path) -> None:
    connectivity = SchematicConnectivity(
        source_file="data/raw/iphone/logan/p1/sch/board.pdf",
        companions=CompanionManifest(boardview="board.brd"),
        sources_used=["boardview", "pdf_geometry"],
        nets={
            "EDP_AUXP": [
                PinNetBinding("U1", "A12", "EDP_AUXP", "boardview"),
                PinNetBinding("R1", "1", "EDP_AUXP", "boardview"),
            ],
            "GND": [PinNetBinding("U1", "B1", "GND", "boardview")],
        },
        parts={
            "U1": [
                PinNetBinding("U1", "A12", "EDP_AUXP", "boardview"),
                PinNetBinding("U1", "B1", "GND", "boardview"),
            ],
            "J1": [PinNetBinding("J1", "1", "EDP_AUXP", "boardview")],
        },
        pages=[
            PageConnectivity(
                page=3,
                source="pdf_geometry",
                connectors=(
                    ConnectorBinding(
                        refdes="J1",
                        module="DISPLAY",
                        nets=("EDP_AUXP",),
                        evidence="pdf_geometry",
                    ),
                ),
                module_nets={"DISPLAY": ["EDP_AUXP", "GND"]},
            )
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(connectivity.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_load_and_trace_net(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    sidecar = processed / "iphone" / "logan" / "p1" / "sch" / "board.connectivity.json"
    _write_sidecar(sidecar)
    layout = _layout(processed)

    docs = load_connectivity_documents(
        processed, layout, product="iphone", project="logan", build="p1"
    )
    assert len(docs) == 1
    assert docs[0].product == "iphone"
    assert docs[0].project == "logan"

    cq = ConnectivityQuery(documents=docs, layout=layout)
    result = cq.trace_net("EDP_AUXP", product="iphone", project="logan", build="p1")
    assert result["found"] is True
    assert result["pin_count"] == 2
    refdes = {p["refdes"] for p in result["pins"]}
    assert refdes == {"U1", "R1"}
    assert all(p["evidence"] == "boardview" for p in result["pins"])


def test_connector_pins_and_module_nets(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_sidecar(processed / "iphone" / "logan" / "p1" / "sch" / "board.connectivity.json")
    cq = open_connectivity_query(
        processed_dir=processed,
        layout=_layout(processed),
    )
    pins = cq.connector_pins("J1", product="iphone", project="logan", build="p1")
    assert pins["found"] is True
    assert pins["pins"][0]["net"] == "EDP_AUXP"
    assert pins["connectors"][0]["module"] == "DISPLAY"

    modules = cq.module_nets("DISPLAY", product="iphone", project="logan", build="p1", page=3)
    assert modules["found"] is True
    assert "EDP_AUXP" in modules["modules"][0]["nets"]


def test_trace_net_missing(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_sidecar(processed / "iphone" / "logan" / "p1" / "sch" / "board.connectivity.json")
    cq = open_connectivity_query(
        processed_dir=processed,
        layout=_layout(processed),
    )
    result = cq.trace_net("NO_SUCH_NET", product="iphone", project="logan", build="p1")
    assert result["found"] is False
    assert result["pins"] == []


def _write_bus_sidecar(path: Path) -> None:
    connectivity = SchematicConnectivity(
        source_file="data/raw/ipad/logan/p1/sch/board.pdf",
        companions=CompanionManifest(boardview="board.brd"),
        sources_used=["boardview"],
        nets={
            "DP_TBTSNK1_ML_C_N<0>": [
                PinNetBinding("C2831", "1", "DP_TBTSNK1_ML_C_N<0>", "boardview"),
                PinNetBinding("U9750", "3", "DP_TBTSNK1_ML_C_N<0>", "boardview"),
            ],
            "DP_TBTSNK1_ML_C_N<1>": [
                PinNetBinding("C2833", "1", "DP_TBTSNK1_ML_C_N<1>", "boardview"),
                PinNetBinding("U9750", "4", "DP_TBTSNK1_ML_C_N<1>", "boardview"),
            ],
            "DP_TBTSNK1_ML_C_N<2>": [
                PinNetBinding("C2835", "1", "DP_TBTSNK1_ML_C_N<2>", "boardview"),
            ],
        },
        parts={},
        pages=[],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(connectivity.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_trace_net_bus_index_exact_only(tmp_path: Path) -> None:
    """Asking for ``NAME<1>`` must not dump ``NAME<0>``…``NAME<2>``."""
    processed = tmp_path / "processed"
    _write_bus_sidecar(
        processed / "ipad" / "logan" / "p1" / "sch" / "board.connectivity.json"
    )
    cq = open_connectivity_query(
        processed_dir=processed,
        layout=_layout(processed),
    )
    result = cq.trace_net(
        "DP_TBTSNK1_ML_C_N<1>",
        product="ipad",
        project="logan",
        build="p1",
    )
    assert result["found"] is True
    assert result["resolved_net"] == "DP_TBTSNK1_ML_C_N<1>"
    assert result["match"] == "exact"
    nets = {p["net"] for p in result["pins"]}
    assert nets == {"DP_TBTSNK1_ML_C_N<1>"}
    assert {p["refdes"] for p in result["pins"]} == {"C2833", "U9750"}


def test_trace_net_wrong_bus_index_refuses(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_bus_sidecar(
        processed / "ipad" / "logan" / "p1" / "sch" / "board.connectivity.json"
    )
    cq = open_connectivity_query(
        processed_dir=processed,
        layout=_layout(processed),
    )
    result = cq.trace_net(
        "DP_TBTSNK1_ML_C_N<9>",
        product="ipad",
        project="logan",
        build="p1",
    )
    assert result["found"] is False
    assert result["pins"] == []
    assert "DP_TBTSNK1_ML_C_N<1>" in (result.get("candidates") or [])
    assert "No exact net" in (result.get("error") or "")


def test_trace_net_bare_bus_base_refuses_without_index(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_bus_sidecar(
        processed / "ipad" / "logan" / "p1" / "sch" / "board.connectivity.json"
    )
    cq = open_connectivity_query(
        processed_dir=processed,
        layout=_layout(processed),
    )
    result = cq.trace_net(
        "DP_TBTSNK1_ML_C_N",
        product="ipad",
        project="logan",
        build="p1",
    )
    assert result["found"] is False
    assert result["match"] == "ambiguous_bus"
    assert result["pins"] == []
    assert len(result.get("candidates") or []) >= 2
