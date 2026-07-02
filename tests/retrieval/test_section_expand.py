"""Tests for retrieval-time section expansion."""

from __future__ import annotations

from ee_wiki.retrieval.hybrid.engine import HybridChunk
from ee_wiki.retrieval.section_expand import (
    build_section_index,
    expand_retrieved_sections,
    merge_section_chunks,
    section_key,
)


def _chunk(chunk_id: str, content: str) -> HybridChunk:
    return HybridChunk(
        chunk_id=chunk_id,
        content=content,
        metadata={"title": "manual"},
        citation={"source_file": "note/manual.md", "chunk_id": chunk_id, "page": 0, "excerpt": content[:40]},
    )


def test_section_key_strips_window_suffix() -> None:
    assert section_key("manual__power__w02") == "manual__power"
    assert section_key("manual__get-dut-sn") == "manual__get-dut-sn"


def test_merge_section_chunks_preserves_order() -> None:
    siblings = [
        _chunk("manual__get-dut-sn", "## Get DUT SN:\n\n```shell"),
        _chunk("manual__get-dut-sn__w01", "sysconfig read -k SrNm"),
        _chunk("manual__get-dut-sn__w02", "sn\nsyscfg print mlb\n```"),
    ]
    merged = merge_section_chunks(siblings)

    assert merged.chunk_id == "manual__get-dut-sn"
    assert "sysconfig read -k SrNm" in merged.content
    assert "syscfg print mlb" in merged.content


def test_expand_retrieved_sections_deduplicates_same_section() -> None:
    index = build_section_index(
        [
            _chunk("manual__get-dut-sn", "header"),
            _chunk("manual__get-dut-sn__w01", "commands"),
            _chunk("manual__other", "other"),
        ]
    )
    hits = [
        _chunk("manual__get-dut-sn__w01", "commands"),
        _chunk("manual__get-dut-sn", "header"),
        _chunk("manual__other", "other"),
    ]

    expanded = expand_retrieved_sections(hits, index)

    assert len(expanded) == 2
    assert expanded[0].chunk_id == "manual__get-dut-sn"
    assert "header" in expanded[0].content
    assert "commands" in expanded[0].content
    assert expanded[1].chunk_id == "manual__other"
