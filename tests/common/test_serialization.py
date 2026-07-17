"""Tests for metadata serialization."""

from __future__ import annotations

from ee_wiki.common.serialization import (
    chunk_from_dict,
    chunk_to_dict,
    metadata_from_dict,
    metadata_to_dict,
)
from ee_wiki.common.types import Chunk, Citation, Metadata, PageMetadata


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
    assert "supply_voltage" not in data
    assert "pin_count" not in data
    assert "package" not in data


def test_datasheet_metadata_includes_structured_fields() -> None:
    metadata = Metadata(
        project="global",
        build="global",
        document_type="datasheet",
        title="stm32f407",
        source_file="data/raw/global/datasheet/stm32f407.pdf",
        target_file="data/processed/global/datasheet/stm32f407.md",
        supply_voltage=["3.3V", "2V-3.6V"],
        pin_count=144,
        package="LQFP144",
        interfaces=["I2C", "SPI"],
    )
    data = metadata_to_dict(metadata)
    assert data["supply_voltage"] == ["3.3V", "2V-3.6V"]
    assert data["pin_count"] == 144
    assert data["package"] == "LQFP144"
    assert data["interfaces"] == ["I2C", "SPI"]
    assert "major_components" not in data
    assert "pages" not in data
    restored = metadata_from_dict(data)
    assert restored == metadata


def test_schematic_metadata_includes_pages() -> None:
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type="schematic",
        title="main",
        source_file="data/raw/logan/p1/sch/main.pdf",
        target_file="data/processed/logan/p1/sch/main.md",
        major_components=["U0902", "U101"],
        nets=["VBAT"],
        interfaces=["I2C1"],
        pages=[
            PageMetadata(page=1, major_components=["U0902"], nets=["VBAT"], interfaces=["I2C1"]),
            PageMetadata(page=2, major_components=["U101"], nets=["GND"], interfaces=[]),
        ],
    )
    data = metadata_to_dict(metadata)
    assert data["pages"] == [
        {
            "page": 1,
            "major_components": ["U0902"],
            "nets": ["VBAT"],
            "interfaces": ["I2C1"],
        },
        {
            "page": 2,
            "major_components": ["U101"],
            "nets": ["GND"],
            "interfaces": [],
        },
    ]
    restored = metadata_from_dict(data)
    assert restored.pages == metadata.pages


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


def test_metadata_from_dict_strips_schematic_fields_for_note() -> None:
    """Hand-edited sidecars must not load schematic fields into note metadata."""
    data = {
        "project": "logan",
        "build": "p1",
        "document_type": "engineering_note",
        "title": "manual",
        "source_file": "data/raw/logan/p1/note/manual.md",
        "major_components": ["U0902"],
        "nets": ["VBAT"],
        "interfaces": ["I2C1"],
        "pages": [{"page": 1, "major_components": ["U0902"], "nets": ["VBAT"], "interfaces": []}],
    }
    restored = metadata_from_dict(data)
    assert restored.major_components is None
    assert restored.nets is None
    assert restored.interfaces is None
    assert restored.pages is None


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
        heading_path="board report › 页 1",
    )
    restored = chunk_from_dict(chunk_to_dict(chunk))
    assert restored == chunk
