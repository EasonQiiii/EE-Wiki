"""Tests for incremental ingest sync logic."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.pipeline import ingest_file
from ee_wiki.ingestion.sync import needs_ingest
from ee_wiki.knowledge.store.processed import write_processed_document


@pytest.fixture
def sync_config(app_config, tmp_path: Path) -> AppConfig:
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


def test_needs_ingest_when_no_sidecar(sync_config: AppConfig) -> None:
    raw_path = sync_config.raw_dir / "logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# hello\n", encoding="utf-8")
    assert needs_ingest(raw_path, sync_config.data_layout) is True


def test_skip_when_fingerprint_matches(sync_config: AppConfig, repo_root: Path) -> None:
    raw_path = sync_config.raw_dir / "logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# hello\n", encoding="utf-8")
    ingest_file(raw_path, sync_config)
    assert needs_ingest(raw_path, sync_config.data_layout) is False


def test_reingest_when_file_size_changes(sync_config: AppConfig) -> None:
    raw_path = sync_config.raw_dir / "logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# hello\n", encoding="utf-8")

    layout = sync_config.data_layout
    content_path = layout.processed_dir / "logan/p1/note/sample.md"
    metadata_path = content_path.with_suffix(".md.meta.json")
    content_path.parent.mkdir(parents=True)
    content_path.write_text("# hello\n", encoding="utf-8")
    metadata_path.write_text(
        json.dumps({"source_mtime": 1.0, "source_size": 1}) + "\n",
        encoding="utf-8",
    )

    assert needs_ingest(raw_path, layout) is True


def test_force_always_reingests(sync_config: AppConfig) -> None:
    raw_path = sync_config.raw_dir / "logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# hello\n", encoding="utf-8")
    ingest_file(raw_path, sync_config)
    assert needs_ingest(raw_path, sync_config.data_layout, force=True) is True


def test_write_processed_records_fingerprint(sync_config: AppConfig) -> None:
    raw_path = sync_config.raw_dir / "logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("content\n", encoding="utf-8")
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type="engineering_note",
        title="sample",
        source_file="data/raw/logan/p1/note/sample.md",
    )
    document = StandardDocument(content="content\n", metadata=metadata, source_ref=str(raw_path))
    paths = write_processed_document(document, raw_path, sync_config.data_layout)
    meta = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    stat = raw_path.stat()
    assert meta["source_mtime"] == stat.st_mtime
    assert meta["source_size"] == stat.st_size
