"""Tests for schematic connectivity HTTP routes and the authority gate."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_connectivity_query
from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.connectivity.authority import AuthorityPolicy
from ee_wiki.connectivity.query import ConnectivityQuery
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


def _write_sidecar(path: Path, *, evidence: str = "boardview") -> None:
    connectivity = SchematicConnectivity(
        source_file="data/raw/iphone/logan/p1/sch/board.pdf",
        companions=CompanionManifest(boardview="board.brd"),
        sources_used=[evidence, "pdf_geometry"],
        nets={
            "EDP_AUXP": [
                PinNetBinding("U1", "A12", "EDP_AUXP", evidence),
                PinNetBinding("R1", "1", "EDP_AUXP", evidence),
            ],
        },
        parts={
            "J1": [PinNetBinding("J1", "1", "EDP_AUXP", evidence)],
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


def _real_cq(tmp_path: Path, *, evidence: str = "boardview") -> ConnectivityQuery:
    processed = tmp_path / "processed"
    _write_sidecar(
        processed / "iphone" / "logan" / "p1" / "sch" / "board.connectivity.json",
        evidence=evidence,
    )
    layout = _layout(processed)
    docs = load_connectivity_documents(
        processed, layout, product="iphone", project="logan", build="p1"
    )
    return ConnectivityQuery(documents=docs, layout=layout, authority=AuthorityPolicy())


def _client(cq: ConnectivityQuery | None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_connectivity_query] = lambda: cq
    return TestClient(app)


def test_trace_net_http_authoritative(tmp_path: Path) -> None:
    client = _client(_real_cq(tmp_path))
    response = client.get(
        "/v1/schematic/connectivity/net",
        params={"q": "EDP_AUXP", "product": "iphone", "project": "logan", "build": "p1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert payload["authoritative"] is True
    assert payload["authority"] == "authoritative"
    assert {p["refdes"] for p in payload["pins"]} == {"U1", "R1"}


def test_trace_net_http_advisory_refused(tmp_path: Path) -> None:
    # Only geometry/OCR evidence exists → gate must refuse with 409.
    client = _client(_real_cq(tmp_path, evidence="pdf_geometry"))
    response = client.get(
        "/v1/schematic/connectivity/net",
        params={"q": "EDP_AUXP", "product": "iphone", "project": "logan", "build": "p1"},
    )
    assert response.status_code == 409


def test_connectivity_503_when_missing() -> None:
    client = _client(None)
    response = client.get("/v1/schematic/connectivity/net", params={"q": "X"})
    assert response.status_code == 503


def test_trace_net_404(tmp_path: Path) -> None:
    client = _client(_real_cq(tmp_path))
    response = client.get(
        "/v1/schematic/connectivity/net",
        params={"q": "MISSING", "product": "iphone", "project": "logan", "build": "p1"},
    )
    assert response.status_code == 404


def test_connector_pins_and_module_nets_http(tmp_path: Path) -> None:
    client = _client(_real_cq(tmp_path))

    pins = client.get(
        "/v1/schematic/connectivity/pins",
        params={"q": "J1", "product": "iphone", "project": "logan", "build": "p1"},
    )
    assert pins.status_code == 200
    assert pins.json()["resolved_refdes"] == "J1"
    assert pins.json()["authoritative"] is True

    modules = client.get(
        "/v1/schematic/connectivity/module-nets",
        params={"q": "DISPLAY", "product": "iphone", "project": "logan", "build": "p1", "page": 3},
    )
    assert modules.status_code == 200
    body = modules.json()
    assert body["modules"][0]["module"] == "DISPLAY"
    # Module zone labels are geometric hints — never board-verified truth.
    assert body["authoritative"] is False
    assert body["authority"] == "advisory"
