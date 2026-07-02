"""Tests for generation context formatting."""

from __future__ import annotations

from ee_wiki.generation.context import chunks_to_citations, format_context_blocks
from ee_wiki.retrieval.hybrid.engine import HybridChunk


def test_format_context_blocks_numbers_chunks() -> None:
    chunks = [
        HybridChunk(
            chunk_id="a__1",
            content="First chunk body.",
            metadata={"project": "logan", "build": "p1", "document_type": "engineering_note"},
            citation={
                "source_file": "data/raw/logan/p1/note/a.md",
                "chunk_id": "a__1",
                "page": 0,
                "excerpt": "First",
            },
        ),
        HybridChunk(
            chunk_id="b__2",
            content="Second chunk body.",
            metadata={"project": "logan", "build": "p1", "document_type": "schematic"},
            citation={
                "source_file": "data/raw/logan/p1/sch/b.pdf",
                "chunk_id": "b__2",
                "page": 2,
                "excerpt": "Second",
            },
        ),
    ]

    rendered = format_context_blocks(chunks)
    assert "[1] source=data/raw/logan/p1/note/a.md" in rendered
    assert "First chunk body." in rendered
    assert "[2] source=data/raw/logan/p1/sch/b.pdf page=2" in rendered
    assert "Second chunk body." in rendered


def test_chunks_to_citations_maps_fields() -> None:
    chunks = [
        HybridChunk(
            chunk_id="sch__rmii",
            content="RMII notes",
            metadata={},
            citation={
                "source_file": "data/raw/logan/p1/sch/board.pdf",
                "chunk_id": "sch__rmii",
                "page": 3,
                "excerpt": "RMII",
            },
        )
    ]
    citations = chunks_to_citations(chunks)
    assert len(citations) == 1
    assert citations[0].source_file.endswith("board.pdf")
    assert citations[0].chunk_id == "sch__rmii"
    assert citations[0].page == 3
