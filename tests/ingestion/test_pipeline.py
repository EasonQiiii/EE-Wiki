"""Tests for the ingestion pipeline."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.ingestion.pipeline import IngestionError, ingest_file, ingest_path


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
    source = repo_root / "tests/fixtures/raw/logan/p1/note/sample.md"
    raw_path = ingest_config.raw_dir / "logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    result = ingest_file(raw_path, ingest_config)
    assert result.processed.content_path.exists()
    assert result.processed.metadata_path.exists()
    meta = json.loads(result.processed.metadata_path.read_text(encoding="utf-8"))
    assert meta["title"] == "sample"


def test_ingest_path_rejects_unsupported_suffix(ingest_config: AppConfig) -> None:
    raw_path = ingest_config.raw_dir / "logan/p1/note/file.key"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("x", encoding="utf-8")
    with pytest.raises(IngestionError, match="Unsupported"):
        ingest_file(raw_path, ingest_config)


def test_ingest_path_directory(ingest_config: AppConfig, repo_root: Path) -> None:
    for name in ("a.md", "b.md"):
        path = ingest_config.raw_dir / "logan/p1/note" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {name}\n", encoding="utf-8")

    results = ingest_path(ingest_config.raw_dir / "logan", ingest_config)
    assert len(results) == 2
