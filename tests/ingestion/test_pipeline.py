"""Tests for the ingestion pipeline."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.ingestion.pipeline import IngestionError, IngestResult, ingest_file, ingest_path


@pytest.fixture
def ingest_config(app_config, tmp_path: Path) -> AppConfig:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    raw_dir.mkdir()
    processed_dir.mkdir()
    layout = replace(
        app_config.data_layout,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )
    return replace(app_config, raw_dir=raw_dir, processed_dir=processed_dir, data_layout=layout)


def test_ingest_file_end_to_end(ingest_config: AppConfig, repo_root: Path) -> None:
    source = repo_root / "tests/fixtures/raw/iphone/logan/p1/note/sample.md"
    raw_path = ingest_config.raw_dir / "iphone/logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    result = ingest_file(raw_path, ingest_config)
    assert result.processed.content_path.exists()
    assert result.processed.metadata_path.exists()
    meta = json.loads(result.processed.metadata_path.read_text(encoding="utf-8"))
    assert meta["title"] == "sample"
    assert "target_file" in meta
    assert "major_components" not in meta


def test_ingest_txt_file_uses_markdown_parser(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "iphone/logan/p1/note/readme.txt"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# Readme\n\nPlain text body.\n", encoding="utf-8")

    result = ingest_file(raw_path, ingest_config)
    assert result.processed.content_path.name == "readme.txt"
    body = result.processed.content_path.read_text(encoding="utf-8")
    assert "Plain text body" in body
    meta = json.loads(result.processed.metadata_path.read_text(encoding="utf-8"))
    assert meta["document_type"] == "engineering_note"


def test_ingest_path_rejects_unsupported_suffix(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "iphone/logan/p1/note/archive.zip"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_bytes(b"zip")
    with pytest.raises(IngestionError, match="Unsupported"):
        ingest_file(raw_path, ingest_config)


def test_ingest_path_directory(ingest_config: AppConfig, repo_root: Path) -> None:
    for name in ("a.md", "b.md"):
        path = ingest_config.raw_dir / "iphone/logan/p1/note" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")

    run = ingest_path(ingest_config.raw_dir / "iphone", ingest_config)
    assert len(run.ingested) == 2
    assert len(run.skipped) == 0


def test_ingest_path_skips_unchanged(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "iphone/logan/p1/note/a.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# a\n", encoding="utf-8")

    first = ingest_path(ingest_config.raw_dir, ingest_config)
    assert len(first.ingested) == 1
    assert len(first.skipped) == 0

    second = ingest_path(ingest_config.raw_dir, ingest_config)
    assert len(second.ingested) == 0
    assert len(second.skipped) == 1
    assert len(second.removed) == 0


def test_ingest_path_continues_after_file_failure(
    ingest_config: AppConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note_dir = ingest_config.raw_dir / "iphone/logan/p1/note"
    note_dir.mkdir(parents=True)
    (note_dir / "good.md").write_text("# good\n", encoding="utf-8")
    (note_dir / "bad.md").write_text("# bad\n", encoding="utf-8")

    original_ingest_file = ingest_file

    def _patched_ingest_file(raw_path: Path, config: AppConfig) -> IngestResult:
        if raw_path.name == "bad.md":
            raise IngestionError("boom")
        return original_ingest_file(raw_path, config)

    monkeypatch.setattr(
        "ee_wiki.ingestion.pipeline.ingest_file",
        _patched_ingest_file,
    )

    run = ingest_path(note_dir, ingest_config)
    assert len(run.ingested) == 1
    assert run.ingested[0].raw_path.name == "good.md"
    assert len(run.failed) == 1
    assert run.failed[0].raw_path.name == "bad.md"
    assert run.failed[0].message == "boom"
