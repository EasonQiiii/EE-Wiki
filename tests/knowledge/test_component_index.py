"""Tests for component index build and persistence."""

from __future__ import annotations

from ee_wiki.common.types import Chunk, Citation, Metadata
from ee_wiki.knowledge.indexer.component_index import (
    build_component_index,
    load_component_index,
    save_component_index,
)


def _chunk(
    *,
    chunk_id: str,
    document_type: str = "schematic",
    major_components: list[str] | None = None,
    keywords: list[str] | None = None,
    project: str = "logan",
    build: str = "p1",
) -> Chunk:
    metadata = Metadata(
        project=project,
        build=build,
        document_type=document_type,
        title="board",
        source_file="data/raw/logan/p1/sch/board.pdf",
        target_file="data/processed/logan/p1/sch/board.md",
        major_components=major_components,
        keywords=keywords or [],
    )
    return Chunk(
        chunk_id=chunk_id,
        content="sample content",
        metadata=metadata,
        citation=Citation(
            source_file=metadata.source_file,
            chunk_id=chunk_id,
            page=1,
            excerpt="sample content",
        ),
    )


def test_build_component_index_indexes_designators_and_part_numbers() -> None:
    chunks = [
        _chunk(chunk_id="board__p001", major_components=["U101", "R205"]),
        _chunk(
            chunk_id="stm32__p001",
            document_type="datasheet",
            major_components=None,
            keywords=["STM32F407VGT6", "168MHZ"],
            project="global",
            build="global",
        ),
    ]

    index = build_component_index(chunks)

    assert "U101" in index.entries
    assert index.entries["U101"][0].kind == "designator"
    assert index.entries["U101"][0].chunk_id == "board__p001"
    assert "STM32F407VGT6" in index.entries
    assert index.entries["STM32F407VGT6"][0].kind == "part_number"
    assert "R205" in index.entries


def test_build_component_index_deduplicates_chunk_keys() -> None:
    chunks = [
        _chunk(chunk_id="board__p001", major_components=["U101"]),
        _chunk(chunk_id="board__p001", major_components=["U101"]),
    ]

    index = build_component_index(chunks)

    assert len(index.entries["U101"]) == 1


def test_save_and_load_component_index(tmp_path) -> None:
    chunks = [_chunk(chunk_id="board__p001", major_components=["U101"])]
    save_component_index(chunks, tmp_path)
    loaded = load_component_index(tmp_path)

    assert loaded is not None
    assert loaded.entries["U101"][0].chunk_id == "board__p001"
