"""Tests for processed mirror persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.parsers.markdown import parse_markdown
from ee_wiki.knowledge.store.processed import write_processed_document


@pytest.fixture
def layout_with_tmp_dirs(data_layout, tmp_path: Path):
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    from dataclasses import replace

    return replace(
        data_layout,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )


def test_write_processed_mirror(layout_with_tmp_dirs, repo_root: Path) -> None:
    layout = layout_with_tmp_dirs
    raw_path = layout.raw_dir / "logan" / "p1" / "note" / "sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# Title\n\nBody\n", encoding="utf-8")

    document = parse_markdown(raw_path, layout, repo_root=repo_root)
    paths = write_processed_document(document, raw_path, layout, repo_root=repo_root)

    assert paths.content_path == layout.processed_dir / "logan/p1/note/sample.md"
    assert paths.metadata_path == layout.processed_dir / "logan/p1/note/sample.md.meta.json"
    assert paths.content_path.read_text(encoding="utf-8") == document.content

    meta = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    assert meta["project"] == "logan"
    assert meta["build"] == "p1"
    assert meta["document_type"] == "engineering_note"
    assert meta["target_file"] == "data/processed/logan/p1/note/sample.md"
    assert "major_components" not in meta
    assert "nets" not in meta
    assert "interfaces" not in meta


def test_write_processed_preserves_metadata_fields(layout_with_tmp_dirs) -> None:
    layout = layout_with_tmp_dirs
    raw_path = layout.raw_dir / "logan" / "p1" / "note" / "sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("content\n", encoding="utf-8")

    metadata = Metadata(
        project="logan",
        build="p1",
        document_type="engineering_note",
        title="sample",
        source_file="data/raw/logan/p1/note/sample.md",
        keywords=["test"],
    )
    document = StandardDocument(content="content\n", metadata=metadata, source_ref=str(raw_path))
    paths = write_processed_document(document, raw_path, layout)
    meta = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    assert meta["keywords"] == ["test"]
    assert meta["target_file"] == "data/processed/logan/p1/note/sample.md"
