"""Tests for knowledge-graph store, build, and query (V3 P1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.graph import (
    EDGE_CONNECTS_TO,
    EDGE_SAME_AS,
    NODE_COMPONENT,
    GraphQuery,
    JsonlGraphStore,
    KnowledgeGraph,
    build_graph_from_chunks,
    graph_exists,
    open_query,
)
from ee_wiki.graph.ids import component_node_id, net_node_id, part_node_id
from ee_wiki.graph.store import GraphStoreError
from ee_wiki.knowledge.indexer.component_index import (
    ComponentHit,
    ComponentIndex,
    build_component_index,
)


def _layout(tmp_path: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={"sch": "schematic", "note": "engineering_note"},
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )


def _chunk(
    *,
    chunk_id: str,
    product: str,
    project: str,
    build: str,
    source_file: str,
    document_type: str = "schematic",
    major_components: list[str] | None = None,
    nets: list[str] | None = None,
    keywords: list[str] | None = None,
    page: int = 1,
    title: str = "Schematic",
) -> Chunk:
    metadata = Metadata(
        product=product,
        project=project,
        build=build,
        document_type=document_type,
        title=title,
        source_file=source_file,
        page=page,
        major_components=major_components,
        nets=nets,
        keywords=list(keywords or []),
    )
    return Chunk(
        chunk_id=chunk_id,
        content="U101 connects to NET_VCC",
        metadata=metadata,
        citation=Citation(
            source_file=source_file,
            chunk_id=chunk_id,
            page=page,
            excerpt="U101 connects to NET_VCC",
        ),
    )


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    return [
        _chunk(
            chunk_id="c1",
            product="acme",
            project="demo",
            build="p1",
            source_file="acme/demo/p1/sch/power.md",
            major_components=["U101", "C10"],
            nets=["NET_VCC", "GND"],
            keywords=["STM32F407VGT6"],
            page=1,
        ),
        _chunk(
            chunk_id="c2",
            product="acme",
            project="demo",
            build="common",
            source_file="acme/demo/common/note/arch.md",
            document_type="engineering_note",
            keywords=["STM32F407VGT6"],
            page=0,
            title="Architecture",
        ),
        _chunk(
            chunk_id="c3",
            product="global",
            project="global",
            build="global",
            source_file="global/datasheet/stm32.md",
            document_type="datasheet",
            keywords=["STM32F407VGT6"],
            page=0,
            title="STM32 datasheet",
        ),
    ]


def test_build_creates_component_net_document_scope_nodes(
    sample_chunks: list[Chunk], tmp_path: Path
) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks(sample_chunks, layout=layout)

    assert component_node_id("acme", "demo", "p1", "U101") in graph.nodes
    assert net_node_id("acme", "demo", "p1", "NET_VCC") in graph.nodes
    assert part_node_id("STM32F407VGT6") in graph.nodes
    assert "product:acme" in graph.nodes
    assert "project:acme/demo" in graph.nodes
    assert "build:acme/demo/p1" in graph.nodes
    assert any(n.type == "Document" for n in graph.nodes.values())

    edge_types = {e.type for e in graph.edges}
    assert EDGE_CONNECTS_TO in edge_types
    assert EDGE_SAME_AS in edge_types


def test_connects_to_links_designators_to_nets(
    sample_chunks: list[Chunk], tmp_path: Path
) -> None:
    graph = build_graph_from_chunks(sample_chunks, layout=_layout(tmp_path))
    u101 = component_node_id("acme", "demo", "p1", "U101")
    net = net_node_id("acme", "demo", "p1", "NET_VCC")
    connects = [
        e
        for e in graph.edges
        if e.type == EDGE_CONNECTS_TO
        and {e.source, e.target} == {u101, net}
    ]
    assert len(connects) == 1


def test_same_as_links_designator_to_part(
    sample_chunks: list[Chunk], tmp_path: Path
) -> None:
    graph = build_graph_from_chunks(sample_chunks, layout=_layout(tmp_path))
    u101 = component_node_id("acme", "demo", "p1", "U101")
    part = part_node_id("STM32F407VGT6")
    same = [
        e
        for e in graph.edges
        if e.type == EDGE_SAME_AS and {e.source, e.target} == {u101, part}
    ]
    assert len(same) == 1


def test_jsonl_store_roundtrip(sample_chunks: list[Chunk], tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks(sample_chunks, layout=layout)
    graph_dir = tmp_path / "graph"
    store = JsonlGraphStore()
    manifest = store.save_graph(graph_dir, graph=graph)
    assert graph_exists(graph_dir)
    assert manifest.node_count == len(graph.nodes)

    loaded = store.load_graph(graph_dir)
    assert len(loaded.nodes) == len(graph.nodes)
    assert len(loaded.edges) == len(graph.edges)
    assert component_node_id("acme", "demo", "p1", "U101") in loaded.adjacency


def test_open_graph_missing_raises(tmp_path: Path) -> None:
    store = JsonlGraphStore()
    with pytest.raises(GraphStoreError, match="incomplete"):
        store.open_graph(tmp_path / "missing")


def test_neighbors_and_path(sample_chunks: list[Chunk], tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks(sample_chunks, layout=layout)
    query = GraphQuery(graph, layout=layout, scope_inheritance=True)

    u101 = component_node_id("acme", "demo", "p1", "U101")
    neighbors = query.neighbors(
        u101, product="acme", project="demo", build="p1", max_hops=1
    )
    neighbor_ids = {n["id"] for n in neighbors}
    assert net_node_id("acme", "demo", "p1", "NET_VCC") in neighbor_ids
    assert all("scope" in n for n in neighbors)

    path = query.path(
        u101,
        net_node_id("acme", "demo", "p1", "GND"),
        product="acme",
        project="demo",
        build="p1",
        edge_types=[EDGE_CONNECTS_TO],
    )
    assert path is not None
    assert path[0]["id"] == u101
    assert path[-1]["id"] == net_node_id("acme", "demo", "p1", "GND")


def test_filter_by_scope_inheritance(sample_chunks: list[Chunk], tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks(sample_chunks, layout=layout)
    query = open_query(graph, layout=layout, scope_inheritance=True)

    nodes = query.filter_by_scope(
        product="acme", project="demo", build="p1", node_types=[NODE_COMPONENT]
    )
    scopes = {n["scope"] for n in nodes}
    # build designators + global part node via inheritance
    assert "build" in scopes
    assert "global" in scopes

    no_inherit = GraphQuery(graph, layout=layout, scope_inheritance=False)
    strict = no_inherit.filter_by_scope(
        product="acme", project="demo", build="p1", node_types=[NODE_COMPONENT]
    )
    assert all(
        n["product"] == "acme" and n["project"] == "demo" and n["build"] == "p1"
        for n in strict
    )


def test_filter_by_scope_excludes_other_product_same_slugs(tmp_path: Path) -> None:
    """Identical project/build slugs under two products must not leak."""
    layout = _layout(tmp_path)
    chunks = [
        _chunk(
            chunk_id="a1",
            product="acme",
            project="demo",
            build="p1",
            source_file="acme/demo/p1/sch/a.md",
            major_components=["U101"],
            nets=["NET_VCC"],
        ),
        _chunk(
            chunk_id="b1",
            product="beta",
            project="demo",
            build="p1",
            source_file="beta/demo/p1/sch/b.md",
            major_components=["U900"],
            nets=["NET_VCC"],
        ),
    ]
    graph = build_graph_from_chunks(chunks, layout=layout)
    query = open_query(graph, layout=layout, scope_inheritance=True)
    nodes = query.filter_by_scope(
        product="acme", project="demo", build="p1", node_types=[NODE_COMPONENT]
    )
    ids = {n["id"] for n in nodes}
    assert component_node_id("acme", "demo", "p1", "U101") in ids
    assert component_node_id("beta", "demo", "p1", "U900") not in ids


def test_build_uses_component_index(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunk = _chunk(
        chunk_id="c1",
        product="acme",
        project="demo",
        build="p1",
        source_file="acme/demo/p1/sch/page.md",
        major_components=["U200"],
        nets=["CLK"],
    )
    index = build_component_index([chunk])
    # Extra part-only hit not present as keyword on a schematic page alone
    extra = ComponentIndex(
        version=1,
        built_at="2026-01-01T00:00:00Z",
        entries={
            **index.entries,
            "EXTRA-PART-99": [
                ComponentHit(
                    key="EXTRA-PART-99",
                    kind="part_number",
                    chunk_id="c1",
                    product="acme",
                    project="demo",
                    build="p1",
                    document_type="schematic",
                    source_file="acme/demo/p1/sch/page.md",
                    page=1,
                    title="Schematic",
                    excerpt="…",
                )
            ],
        },
    )
    graph = build_graph_from_chunks([chunk], layout=layout, component_index=extra)
    assert part_node_id("EXTRA-PART-99") in graph.nodes


def test_package_exports_real_api() -> None:
    import ee_wiki.graph as graph_pkg

    assert hasattr(graph_pkg, "JsonlGraphStore")
    assert hasattr(graph_pkg, "build_and_save_graph")
    assert hasattr(graph_pkg, "GraphQuery")
    assert "ADR 0006" in (graph_pkg.__doc__ or "") or "0006" in (graph_pkg.__doc__ or "")


def test_empty_graph_query() -> None:
    layout = DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={"sch": "schematic"},
        raw_dir=Path("/tmp/raw"),
        processed_dir=Path("/tmp/processed"),
    )
    query = GraphQuery(KnowledgeGraph(), layout=layout)
    assert query.neighbors("missing") == []
    assert query.path("a", "b") is None
    assert query.filter_by_scope(product="acme", project="demo", build="p1") == []
    assert (
        query.resolve_node("U101", product="acme", project="demo", build="p1") is None
    )


def test_resolve_node_from_designator(sample_chunks: list[Chunk], tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    graph = build_graph_from_chunks(sample_chunks, layout=layout)
    query = open_query(graph, layout=layout, scope_inheritance=True)
    resolved = query.resolve_node("U101", product="acme", project="demo", build="p1")
    assert resolved == component_node_id("acme", "demo", "p1", "U101")
    node = query.get_node(resolved, product="acme", project="demo", build="p1")
    assert node is not None
    assert node["type"] == NODE_COMPONENT
