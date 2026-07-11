"""Tests for component lookup helpers."""

from __future__ import annotations

from ee_wiki.knowledge.indexer.component_index import ComponentHit, ComponentIndex
from ee_wiki.retrieval.component_lookup import lookup_tokens, search_components


def _index() -> ComponentIndex:
    return ComponentIndex(
        version=1,
        built_at="2026-01-01T00:00:00Z",
        entries={
            "U101": [
                ComponentHit(
                    key="U101",
                    kind="designator",
                    chunk_id="board__p001",
                    project="logan",
                    build="p1",
                    document_type="schematic",
                    source_file="data/raw/logan/p1/sch/board.pdf",
                    page=1,
                    title="board",
                    excerpt="U101 PHY",
                )
            ],
            "STM32F407VGT6": [
                ComponentHit(
                    key="STM32F407VGT6",
                    kind="part_number",
                    chunk_id="stm32__p001",
                    project="global",
                    build="global",
                    document_type="datasheet",
                    source_file="data/raw/global/datasheet/STM32F407ZGT6.pdf",
                    page=0,
                    title="STM32F407ZGT6",
                    excerpt="168 MHz",
                )
            ],
        },
    )


def test_lookup_tokens_respects_scope(app_config) -> None:
    chunk_ids = lookup_tokens(
        _index(),
        ["U101"],
        layout=app_config.data_layout,
        target_project="logan",
        target_build="p1",
        scope_inheritance=True,
    )

    assert chunk_ids == {"board__p001"}


def test_lookup_tokens_excludes_out_of_scope_build(app_config) -> None:
    chunk_ids = lookup_tokens(
        _index(),
        ["U101"],
        layout=app_config.data_layout,
        target_project="kingboo",
        target_build="p1",
        scope_inheritance=True,
    )

    assert chunk_ids == set()


def test_search_components_returns_hits(app_config) -> None:
    hits = search_components(
        _index(),
        "STM32F407VGT6",
        layout=app_config.data_layout,
        target_project="global",
        target_build="global",
    )

    assert len(hits) == 1
    assert hits[0].chunk_id == "stm32__p001"
