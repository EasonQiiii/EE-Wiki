"""Tests for document chunking."""

from __future__ import annotations

from ee_wiki.common.config import ChunkingConfig
from ee_wiki.common.types import Metadata
from ee_wiki.knowledge.chunker import chunk_processed_record
from ee_wiki.knowledge.loader import ProcessedRecord


def _record(
    *,
    stem: str,
    content: str,
    document_type: str = "engineering_note",
    page: int = 0,
) -> ProcessedRecord:
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type=document_type,
        title=stem,
        source_file=f"data/raw/logan/p1/note/{stem}.md",
        target_file=f"data/processed/logan/p1/note/{stem}.md",
        page=page,
    )
    return ProcessedRecord(
        chunk_id=stem,
        content=content,
        metadata=metadata,
        target_file=metadata.target_file,
    )


def test_prose_splits_by_headings() -> None:
    content = "# Title\n\nIntro text.\n\n## Power\n\nVBAT details.\n\n## Debug\n\nUART notes."
    config = ChunkingConfig()
    chunks = chunk_processed_record(_record(stem="manual", content=content), config)

    assert len(chunks) == 3
    assert chunks[0].chunk_id == "manual__title"
    assert "Intro text" in chunks[0].content
    assert chunks[1].chunk_id == "manual__power"
    assert "VBAT" in chunks[1].content
    assert chunks[2].chunk_id == "manual__debug"


def test_schematic_splits_by_page_separator() -> None:
    content = (
        "# 电子图纸分析报告：board\n\n"
        "U0902 VBAT on page one\n\n"
        "---\n\n"
        "PMIC GND on page two"
    )
    config = ChunkingConfig()
    record = _record(stem="board", content=content, document_type="schematic")
    chunks = chunk_processed_record(record, config)

    assert len(chunks) == 2
    assert chunks[0].chunk_id == "board__p001"
    assert chunks[0].metadata.page == 1
    assert chunks[0].citation.page == 1
    assert "U0902" in chunks[0].content
    assert chunks[1].chunk_id == "board__p002"
    assert "PMIC" in chunks[1].content


def test_long_section_splits_with_overlap() -> None:
    paragraph = "VBAT net connects to U0902. " * 80
    content = f"## Power\n\n{paragraph}"
    config = ChunkingConfig(max_chars=400, overlap_chars=50, min_chars=20)
    chunks = chunk_processed_record(_record(stem="long", content=content), config)

    assert len(chunks) > 1
    assert all(len(chunk.content) <= 400 for chunk in chunks)
    assert chunks[0].chunk_id == "long__power"
    assert chunks[1].chunk_id.startswith("long__power__w")


def test_small_fragments_merge_into_previous() -> None:
    content = "## Main\n\nLong enough section content here.\n\norphan ok"
    config = ChunkingConfig(min_chars=30)
    chunks = chunk_processed_record(_record(stem="frag", content=content), config)

    assert len(chunks) == 1
    assert "orphan ok" in chunks[0].content


def test_citation_excerpt_truncated() -> None:
    content = "## Section\n\n" + ("x" * 300)
    config = ChunkingConfig(excerpt_chars=50)
    chunks = chunk_processed_record(_record(stem="excerpt", content=content), config)

    assert len(chunks[0].citation.excerpt) <= 51
    assert chunks[0].citation.source_file.endswith("excerpt.md")
