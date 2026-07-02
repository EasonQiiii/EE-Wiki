"""Tests for metadata serialization."""

from __future__ import annotations

from ee_wiki.common.serialization import (
    chunk_from_dict,
    chunk_to_dict,
    metadata_from_dict,
    metadata_to_dict,
)
from ee_wiki.common.types import Chunk, Citation, Metadata


def test_note_metadata_omits_schematic_fields() -> None:
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type="engineering_note",
        title="manual",
        source_file="data/raw/logan/p1/note/manual.md",
        target_file="data/processed/logan/p1/note/manual.md",
    )
    data = metadata_to_dict(metadata)
    assert "target_file" in data
    assert "major_components" not in data
    assert "nets" not in data
    assert "interfaces" not in data


def test_schematic_metadata_includes_schematic_fields() -> None:
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type="schematic",
        title="main",
        source_file="data/raw/logan/p1/sch/main.pdf",
        target_file="data/processed/logan/p1/sch/main.md",
        major_components=["U0902"],
        nets=["VBAT"],
        interfaces=["I2C1"],
    )
    data = metadata_to_dict(metadata)
    assert data["major_components"] == ["U0902"]
    assert data["nets"] == ["VBAT"]
    assert data["interfaces"] == ["I2C1"]


def test_metadata_from_dict_roundtrip() -> None:
    original = Metadata(
        project="logan",
        build="p1",
        document_type="engineering_note",
        title="manual",
        source_file="data/raw/logan/p1/note/manual.md",
        target_file="data/processed/logan/p1/note/manual.md",
        source_mtime=123.0,
        source_size=99,
    )
    restored = metadata_from_dict(metadata_to_dict(original))
    assert restored == original


def test_chunk_roundtrip() -> None:
    chunk = Chunk(
        chunk_id="board__p001",
        content="U0902 VBAT",
        metadata=Metadata(
            project="logan",
            build="p1",
            document_type="schematic",
            title="board",
            source_file="data/raw/logan/p1/sch/board.pdf",
            target_file="data/processed/logan/p1/sch/board.md",
            page=1,
        ),
        citation=Citation(
            source_file="data/raw/logan/p1/sch/board.pdf",
            chunk_id="board__p001",
            page=1,
            excerpt="U0902 VBAT",
        ),
    )
    restored = chunk_from_dict(chunk_to_dict(chunk))
    assert restored == chunk
