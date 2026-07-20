"""Tests for Case nodes and edges in the knowledge graph (V3 P2)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.graph import (
    EDGE_CAUSED_BY,
    EDGE_MENTIONS,
    EDGE_RELATED_TO,
    NODE_CASE,
    build_graph_from_chunks,
)
from ee_wiki.graph.ids import case_node_id, component_node_id, net_node_id
from ee_wiki.knowledge.indexer.case_index import CaseIndex, DebugCaseRecord


def _layout(tmp_path: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={"fa": "failure_analysis", "sch": "schematic"},
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )


def test_build_graph_adds_case_nodes_and_edges(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    fa_chunk = Chunk(
        chunk_id="fa1",
        content="No boot. Open solder on U101.",
        metadata=Metadata(
            product="demo",
            project="demo",
            build="p1",
            document_type="failure_analysis",
            title="RMA",
            source_file="demo/p1/fa/rma.md",
            case_id="RMA-100",
            symptom="No boot",
            suspected_nets=["NET_VCC"],
            suspected_parts=["U101"],
            root_cause="Open solder on U101",
            case_citations=["demo/p1/sch/power.md"],
        ),
        citation=Citation(
            source_file="demo/p1/fa/rma.md",
            chunk_id="fa1",
            excerpt="No boot",
        ),
    )
    case_index = CaseIndex(
        version=1,
        built_at="2026-01-01T00:00:00Z",
        cases=(
            DebugCaseRecord(
                case_id="RMA-100",
                product="demo",
                project="demo",
                build="p1",
                title="RMA",
                source_file="demo/p1/fa/rma.md",
                document_type="failure_analysis",
                symptom="No boot",
                suspected_nets=("NET_VCC",),
                suspected_parts=("U101",),
                root_cause="Open solder on U101",
                case_citations=("demo/p1/sch/power.md",),
                chunk_ids=("fa1",),
            ),
        ),
    )
    graph = build_graph_from_chunks(
        [fa_chunk],
        layout=layout,
        case_index=case_index,
    )

    cid = case_node_id("demo", "demo", "p1", "RMA-100")
    assert cid in graph.nodes
    assert graph.nodes[cid].type == NODE_CASE
    assert graph.nodes[cid].attributes.get("symptom") == "No boot"

    u101 = component_node_id("demo", "demo", "p1", "U101")
    net = net_node_id("demo", "demo", "p1", "NET_VCC")
    mentions = [
        e
        for e in graph.edges
        if e.type == EDGE_MENTIONS and e.source == cid
    ]
    assert any(e.target == u101 for e in mentions)
    assert any(e.target == net for e in mentions)

    caused = [
        e
        for e in graph.edges
        if e.type == EDGE_CAUSED_BY and e.source == cid and e.target == u101
    ]
    assert len(caused) == 1

    related = [e for e in graph.edges if e.type == EDGE_RELATED_TO and e.source == cid]
    assert related
