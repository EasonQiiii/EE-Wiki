"""Tests for Markdown parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from ee_wiki.common.errors import PathMetadataError
from ee_wiki.ingestion.parsers.markdown import (
    MarkdownParserError,
    normalize_markdown,
    parse_markdown,
)


def test_normalize_markdown_line_endings() -> None:
    assert normalize_markdown("a\r\nb\r") == "a\nb\n"


def test_parse_markdown_fixture(data_layout, repo_root: Path, tmp_path: Path) -> None:
    from dataclasses import replace

    layout = replace(
        data_layout,
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )
    source = repo_root / "tests/fixtures/raw/iphone/logan/p1/note/sample.md"
    raw_path = layout.raw_dir / "iphone/logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    document = parse_markdown(raw_path, layout, repo_root=repo_root)
    assert document.metadata.project == "logan"
    assert document.metadata.build == "p1"
    assert document.metadata.document_type == "engineering_note"
    assert document.metadata.title == "sample"
    assert "# Sample Engineering Note" in document.content
    assert document.source_ref.endswith("sample.md")


def test_parse_markdown_requires_valid_layout(data_layout, tmp_path: Path) -> None:
    from dataclasses import replace

    layout = replace(
        data_layout,
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )
    bad_path = layout.raw_dir / "orphan.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("# orphan\n", encoding="utf-8")
    with pytest.raises(PathMetadataError):
        parse_markdown(bad_path, layout)


def test_parse_markdown_missing_file(data_layout) -> None:
    missing = data_layout.raw_dir / "iphone/logan/p1/note/missing.md"
    with pytest.raises(MarkdownParserError, match="Cannot read"):
        parse_markdown(missing, data_layout)
