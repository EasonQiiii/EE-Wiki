"""Tests for optional retrieval↔graph enrichment (V3 P5)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.graph import build_graph_from_chunks, open_query
from ee_wiki.graph.ids import component_node_id, rail_node_id
from ee_wiki.graph.models import (
    EDGE_SUPPLIES,
    NODE_COMPONENT,
    NODE_RAIL,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
)
from ee_wiki.graph.power_tree import open_power_query
from ee_wiki.retrieval.graph_enrichment import (
    _resolve_power_seed,
    build_graph_enrichment,
    format_neighborhood_block,
    try_graph_enrichment,
)


def _layout(tmp_path: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={"sch": "schematic"},
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )


def _chunk() -> Chunk:
    return Chunk(
        chunk_id="board__p001",
        content="U101 connects to NET_VCC",
        metadata=Metadata(
            project="logan",
            build="p1",
            document_type="schematic",
            title="board",
            source_file="data/raw/logan/p1/sch/board.pdf",
            page=1,
            major_components=["U101"],
            nets=["NET_VCC"],
            keywords=["U101", "NET_VCC"],
        ),
        citation=Citation(
            source_file="data/raw/logan/p1/sch/board.pdf",
            chunk_id="board__p001",
            page=1,
            excerpt="U101 connects to NET_VCC",
        ),
    )


def test_format_neighborhood_block_empty() -> None:
    assert format_neighborhood_block(seeds=[], neighbors=[]) == ""


def test_build_graph_enrichment_from_tokens(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks([_chunk()], layout=layout)
    gq = open_query(graph, layout=layout, scope_inheritance=True)

    text = build_graph_enrichment(
        "U101 NET_VCC",
        graph_query=gq,
        project="logan",
        build="p1",
        max_hops=1,
        max_nodes=8,
    )

    assert text is not None
    assert "[graph]" in text
    assert "U101" in text.upper() or "component:logan/p1:U101" in text


def test_try_graph_enrichment_respects_flag(app_config, tmp_path: Path) -> None:
    """Default config keeps enrichment off."""
    assert app_config.retrieval.graph_enrichment is False
    assert (
        try_graph_enrichment(
            "U101",
            config=app_config,
            project="logan",
            build="p1",
        )
        is None
    )


def test_format_context_blocks_appends_enrichment() -> None:
    from ee_wiki.generation.context import format_context_blocks
    from ee_wiki.retrieval.hybrid.engine import HybridChunk

    chunk = HybridChunk(
        chunk_id="c1",
        content="body",
        metadata={"project": "logan", "build": "p1", "document_type": "schematic"},
        citation={"source_file": "x.pdf", "chunk_id": "c1", "page": 1, "excerpt": ""},
    )
    text = format_context_blocks(
        [chunk],
        graph_enrichment="[graph] kind=neighborhood\n  seed id=component:logan/p1:U101",
    )
    assert "[1]" in text
    assert "[graph]" in text


def _power_graph() -> KnowledgeGraph:
    """A small directed power tree: U5 -> VBAT -> U0902."""
    g = KnowledgeGraph()
    rail = rail_node_id("logan", "p1", "VBAT")
    reg = component_node_id("logan", "p1", "U5")
    load = component_node_id("logan", "p1", "U0902")
    g.add_node(GraphNode(id=rail, type=NODE_RAIL, project="logan", build="p1",
                         attributes={"name": "VBAT", "role": "output"}))
    g.add_node(GraphNode(id=reg, type=NODE_COMPONENT, project="logan", build="p1",
                         attributes={"name": "U5"}))
    g.add_node(GraphNode(id=load, type=NODE_COMPONENT, project="logan", build="p1",
                         attributes={"name": "U0902"}))
    g.add_edge(GraphEdge(source=reg, target=rail, type=EDGE_SUPPLIES,
                         project="logan", build="p1",
                         attributes={"kind": "regulator_to_rail"}))
    g.add_edge(GraphEdge(source=rail, target=load, type=EDGE_SUPPLIES,
                         project="logan", build="p1",
                         attributes={"kind": "rail_to_load"}))
    return g


def test_power_tree_routing_renders_directed_block(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    gq = open_query(_power_graph(), layout=layout, scope_inheritance=True)

    text = build_graph_enrichment(
        "why is VBAT missing on U0902",
        graph_query=gq,
        project="logan",
        build="p1",
        power_tree=True,
    )

    assert text is not None
    assert "kind=power_tree" in text
    assert "confidence=high" in text
    assert "VBAT" in text
    assert "U0902" in text
    assert "U5" in text
    assert "feeds" in text
    assert "powers" in text
    assert "regulator_to_rail" in text
    assert "rail_to_load" in text


def test_resolve_power_seed_folds_separators(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    gq = open_query(_power_graph(), layout=layout, scope_inheritance=True)
    pw = open_power_query(gq)
    expected = rail_node_id("logan", "p1", "VBAT")
    # Separator variants must all resolve to the same rail node.
    assert _resolve_power_seed(pw, ["V_BAT"], project="logan", build="p1") == expected
    assert _resolve_power_seed(pw, ["VBAT"], project="logan", build="p1") == expected
    assert _resolve_power_seed(pw, ["NOPE"], project="logan", build="p1") is None


def test_power_tree_low_confidence_when_tree_empty(tmp_path: Path) -> None:
    """A resolved seed with no directed edges and no related flag is low-confidence."""
    g = KnowledgeGraph()
    # Lone rail (will be a missing_supplier flag, but for a different node).
    vcc3 = rail_node_id("logan", "p1", "VCC3")
    g.add_node(GraphNode(id=vcc3, type=NODE_RAIL, project="logan", build="p1",
                         attributes={"name": "VCC3", "role": "output"}))
    # Component seed with no supplies edges.
    u7 = component_node_id("logan", "p1", "U7")
    g.add_node(GraphNode(id=u7, type=NODE_COMPONENT, project="logan", build="p1",
                         attributes={"name": "U7"}))

    gq = open_query(g, layout=_layout(tmp_path), scope_inheritance=True)
    text = build_graph_enrichment(
        "U7 供电 missing",
        graph_query=gq,
        project="logan",
        build="p1",
        power_tree=True,
    )
    assert text is not None
    assert "kind=power_tree" in text
    assert "confidence=low" in text
    assert "no directed power edges resolved for this seed" in text


def test_power_tree_routing_disabled_uses_neighborhood(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    gq = open_query(_power_graph(), layout=layout, scope_inheritance=True)

    text = build_graph_enrichment(
        "VBAT missing on U0902",
        graph_query=gq,
        project="logan",
        build="p1",
        power_tree=False,
    )
    assert text is not None
    assert "kind=neighborhood" in text
    assert "kind=power_tree" not in text


def test_power_query_without_seed_falls_back_to_none(tmp_path: Path) -> None:
    """Power-intent query whose tokens resolve to nothing yields no enrichment."""
    g = KnowledgeGraph()
    g.add_node(GraphNode(
        id=component_node_id("logan", "p1", "U101"),
        type=NODE_COMPONENT, project="logan", build="p1",
        attributes={"name": "U101"},
    ))
    gq = open_query(g, layout=_layout(tmp_path), scope_inheritance=True)
    text = build_graph_enrichment(
        "VDD 电压 missing",
        graph_query=gq,
        project="logan",
        build="p1",
        power_tree=True,
    )
    assert text is None
