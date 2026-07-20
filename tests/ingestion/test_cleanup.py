"""Tests for orphaned processed cleanup."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.cleanup import cleanup_orphaned_processed, raw_path_from_source_file
from ee_wiki.ingestion.pipeline import ingest_file, ingest_path
from ee_wiki.knowledge.store.processed import write_processed_document


@pytest.fixture
def cleanup_config(app_config, tmp_path: Path) -> AppConfig:
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


def test_raw_path_from_source_file(cleanup_config: AppConfig) -> None:
    raw = raw_path_from_source_file(
        "data/raw/iphone/logan/p1/note/sample.md",
        cleanup_config.data_layout,
    )
    assert raw == cleanup_config.raw_dir / "iphone/logan/p1/note/sample.md"


def test_cleanup_removes_processed_when_raw_deleted(cleanup_config: AppConfig) -> None:
    raw_path = cleanup_config.raw_dir / "iphone/logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# hello\n", encoding="utf-8")
    ingest_file(raw_path, cleanup_config)

    content_path = cleanup_config.processed_dir / "iphone/logan/p1/note/sample.md"
    meta_path = content_path.with_suffix(".md.meta.json")
    assert content_path.is_file()
    assert meta_path.is_file()

    raw_path.unlink()
    removed = cleanup_orphaned_processed(
        cleanup_config.data_layout,
        raw_scope=cleanup_config.raw_dir,
    )
    assert len(removed) == 1
    assert not content_path.is_file()
    assert not meta_path.is_file()


def test_cleanup_scoped_to_subdirectory(cleanup_config: AppConfig) -> None:
    note_raw = cleanup_config.raw_dir / "iphone/logan/p1/note/keep.md"
    sch_raw = cleanup_config.raw_dir / "iphone/logan/p1/sch/old.pdf"
    note_raw.parent.mkdir(parents=True)
    sch_raw.parent.mkdir(parents=True)
    note_raw.write_text("# keep\n", encoding="utf-8")
    sch_raw.write_bytes(b"%PDF-1.4")

    for path, source in (
        (note_raw, "data/raw/iphone/logan/p1/note/keep.md"),
        (sch_raw, "data/raw/iphone/logan/p1/sch/old.pdf"),
    ):
        metadata = Metadata(
            product="logan",
            project="logan",
            build="p1",
            document_type="engineering_note",
            title=path.stem,
            source_file=source,
        )
        ext = ".md" if path.suffix == ".pdf" else None
        write_processed_document(
            StandardDocument(content="x\n", metadata=metadata, source_ref=str(path)),
            path,
            cleanup_config.data_layout,
            content_extension=ext,
        )

    note_raw.unlink()

    removed = cleanup_orphaned_processed(
        cleanup_config.data_layout,
        raw_scope=cleanup_config.raw_dir / "iphone/logan/p1/sch",
    )
    assert len(removed) == 0
    assert (cleanup_config.processed_dir / "iphone/logan/p1/note/keep.md").is_file()

    removed_all = cleanup_orphaned_processed(
        cleanup_config.data_layout,
        raw_scope=cleanup_config.raw_dir,
    )
    assert len(removed_all) == 1
    assert not (cleanup_config.processed_dir / "iphone/logan/p1/note/keep.md").is_file()
    assert (cleanup_config.processed_dir / "iphone/logan/p1/sch/old.md").is_file()


def test_single_file_ingest_skips_cleanup(cleanup_config: AppConfig) -> None:
    orphan_raw = cleanup_config.raw_dir / "iphone/logan/p1/note/orphan.md"
    active_raw = cleanup_config.raw_dir / "iphone/logan/p1/note/active.md"
    orphan_raw.parent.mkdir(parents=True)
    orphan_raw.write_text("# orphan\n", encoding="utf-8")
    ingest_file(orphan_raw, cleanup_config)
    orphan_raw.unlink()

    active_raw.write_text("# active\n", encoding="utf-8")
    run = ingest_path(active_raw, cleanup_config)
    assert len(run.removed) == 0
    assert (cleanup_config.processed_dir / "iphone/logan/p1/note/orphan.md").is_file()

    full_run = ingest_path(cleanup_config.raw_dir, cleanup_config)
    assert len(full_run.removed) == 1
    assert not (cleanup_config.processed_dir / "iphone/logan/p1/note/orphan.md").is_file()


def test_single_file_ingest_still_works(cleanup_config: AppConfig) -> None:
    raw_path = cleanup_config.raw_dir / "iphone/logan/p1/note/sample.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# hello\n", encoding="utf-8")

    run = ingest_path(raw_path, cleanup_config)
    assert len(run.ingested) == 1
    assert run.ingested[0].processed.content_path.is_file()


def test_cleanup_removes_images_directory(cleanup_config: AppConfig) -> None:
    """When a raw PDF is deleted, its images/ subdirectory is also removed."""
    raw_path = cleanup_config.raw_dir / "iphone/logan/p1/note/report.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# report\n", encoding="utf-8")
    ingest_file(raw_path, cleanup_config)

    content_path = cleanup_config.processed_dir / "iphone/logan/p1/note/report.md"
    images_dir = content_path.parent / "images" / "report"
    images_dir.mkdir(parents=True)
    (images_dir / "report_p1_img0.png").write_bytes(b"PNG")
    (images_dir / "report_p2_img0.png").write_bytes(b"PNG")

    assert images_dir.is_dir()
    assert len(list(images_dir.iterdir())) == 2

    raw_path.unlink()
    removed = cleanup_orphaned_processed(
        cleanup_config.data_layout,
        raw_scope=cleanup_config.raw_dir,
    )
    assert len(removed) == 1
    assert not content_path.is_file()
    assert not images_dir.is_dir()


def test_cleanup_prunes_empty_images_parent(cleanup_config: AppConfig) -> None:
    """The ``images/`` parent directory itself is pruned when empty."""
    raw_path = cleanup_config.raw_dir / "iphone/logan/p1/note/only.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text("# only\n", encoding="utf-8")
    ingest_file(raw_path, cleanup_config)

    content_path = cleanup_config.processed_dir / "iphone/logan/p1/note/only.md"
    images_parent = content_path.parent / "images"
    images_dir = images_parent / "only"
    images_dir.mkdir(parents=True)
    (images_dir / "only_p1_img0.png").write_bytes(b"PNG")

    raw_path.unlink()
    cleanup_orphaned_processed(
        cleanup_config.data_layout,
        raw_scope=cleanup_config.raw_dir,
    )
    assert not images_dir.is_dir()
    assert not images_parent.is_dir()
