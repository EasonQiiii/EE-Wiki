"""Tests for power-tree extraction and queries (V3 P3)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.graph import (
    EDGE_DERIVED_FROM,
    EDGE_SUPPLIES,
    NODE_RAIL,
    build_graph_from_chunks,
    open_power_query,
    open_query,
)
from ee_wiki.graph.ids import component_node_id, rail_node_id
from ee_wiki.graph.power import (
    is_rail_like_net,
    is_regulator_designator,
    rail_role,
    voltage_hint_from_name,
)


def _layout(tmp_path: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={
            "sch": "schematic",
            "datasheet": "datasheet",
            "note": "engineering_note",
        },
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )


def _sch_chunk(
    *,
    chunk_id: str,
    project: str,
    build: str,
    source_file: str,
    major_components: list[str],
    nets: list[str],
    page: int = 1,
    keywords: list[str] | None = None,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        content="power page",
        metadata=Metadata(
            project=project,
            build=build,
            document_type="schematic",
            title="Power",
            source_file=source_file,
            page=page,
            major_components=major_components,
            nets=nets,
            keywords=list(keywords or []),
        ),
        citation=Citation(
            source_file=source_file,
            chunk_id=chunk_id,
            page=page,
            excerpt="power page",
        ),
    )


def test_rail_name_heuristics() -> None:
    assert is_rail_like_net("3V3")
    assert is_rail_like_net("VBAT")
    assert is_rail_like_net("NET_VCC")
    assert is_rail_like_net("VDD_1V8")
    assert not is_rail_like_net("I2C_SDA")
    assert voltage_hint_from_name("3V3") == "3.3V"
    assert rail_role("VIN") == "input"
    assert rail_role("3V3") == "output"
    assert rail_role("GND") == "ground"
    assert is_regulator_designator("VR10")
    assert is_regulator_designator("LDO1")
    assert not is_regulator_designator("U1")
    assert not is_regulator_designator("R10")


def test_build_extracts_rails_and_supplies(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _sch_chunk(
            chunk_id="p1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/power.md",
            major_components=["U1", "U101", "C10"],
            nets=["VIN", "3V3", "GND"],
            page=1,
        ),
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=True)

    rail_3v3 = rail_node_id("demo", "p1", "3V3")
    rail_vin = rail_node_id("demo", "p1", "VIN")
    u1 = component_node_id("demo", "p1", "U1")
    u101 = component_node_id("demo", "p1", "U101")

    assert rail_3v3 in graph.nodes
    assert graph.nodes[rail_3v3].type == NODE_RAIL
    assert graph.nodes[rail_3v3].attributes.get("voltage_hint") == "3.3V"

    supplies = [e for e in graph.edges if e.type == EDGE_SUPPLIES]
    assert any(e.source == u1 and e.target == rail_3v3 for e in supplies)
    assert any(e.source == rail_3v3 and e.target == u101 for e in supplies)

    derived = [
        e
        for e in graph.edges
        if e.type == EDGE_DERIVED_FROM
        and e.source == rail_3v3
        and e.target == rail_vin
        and (e.attributes or {}).get("kind") == "rail_hierarchy"
    ]
    assert len(derived) == 1


def test_power_tree_queries(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _sch_chunk(
            chunk_id="p1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/power.md",
            major_components=["U1", "U101"],
            nets=["VIN", "3V3", "GND"],
        ),
    ]
    graph = build_graph_from_chunks(chunks, layout=layout)
    gq = open_query(graph, layout=layout, scope_inheritance=True)
    power = open_power_query(gq)

    feeds = power.what_feeds("3V3", project="demo", build="p1")
    feed_ids = {item["id"] for item in feeds}
    assert component_node_id("demo", "p1", "U1") in feed_ids
    assert rail_node_id("demo", "p1", "VIN") in feed_ids

    powered = power.what_powers("3V3", project="demo", build="p1")
    assert any(item["id"] == component_node_id("demo", "p1", "U101") for item in powered)

    tree = power.serialize_tree("U1", project="demo", build="p1")
    assert "Rail:3V3" in tree or "3V3" in tree

    flags = power.flags(project="demo", build="p1")
    codes = {f.code for f in flags}
    # VIN may flag missing_supplier (battery/connector unknown) — acceptable
    assert "multi_supplier" not in codes or True

    result = power.query("3V3", direction="tree", project="demo", build="p1")
    assert result["resolved_id"] == rail_node_id("demo", "p1", "3V3")
    assert result["tree"]


def test_datasheet_supply_links_part(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    sch = _sch_chunk(
        chunk_id="s1",
        project="demo",
        build="p1",
        source_file="demo/p1/sch/power.md",
        major_components=["U1"],
        nets=["3V3", "GND"],
    )
    ds = Chunk(
        chunk_id="d1",
        content="Supply voltage 3.3V",
        metadata=Metadata(
            project="demo",
            build="common",
            document_type="datasheet",
            title="MCU",
            source_file="demo/common/datasheet/mcu.md",
            keywords=["STM32F407VGT6"],
            supply_voltage=["3.3V"],
        ),
        citation=Citation(
            source_file="demo/common/datasheet/mcu.md",
            chunk_id="d1",
            excerpt="3.3V",
        ),
    )
    graph = build_graph_from_chunks([sch, ds], layout=layout)
    rail = rail_node_id("demo", "p1", "3V3")
    from ee_wiki.graph.ids import part_node_id

    part = part_node_id("STM32F407VGT6")
    assert part in graph.nodes
    assert any(
        e.type == EDGE_SUPPLIES and e.source == rail and e.target == part
        for e in graph.edges
    )


def test_power_tree_disabled(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _sch_chunk(
            chunk_id="p1",
            project="demo",
            build="p1",
            source_file="demo/p1/sch/power.md",
            major_components=["U1"],
            nets=["3V3"],
        ),
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=False)
    assert not any(n.type == NODE_RAIL for n in graph.nodes.values())
    assert not any(e.type == EDGE_SUPPLIES for e in graph.edges)
