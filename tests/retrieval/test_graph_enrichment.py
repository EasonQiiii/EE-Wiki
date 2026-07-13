"""Tests for optional retrieval↔graph enrichment (V3 P5)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.graph import build_graph_from_chunks, open_query
from ee_wiki.retrieval.graph_enrichment import (
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
