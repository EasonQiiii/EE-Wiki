"""Tests for incremental index sync planning."""

from __future__ import annotations

from ee_wiki.common.types import Metadata
from ee_wiki.knowledge.indexer.store import IndexManifest
from ee_wiki.knowledge.indexer.sync import (
    fingerprints_match,
    plan_index_update,
    record_fingerprint,
)
from ee_wiki.knowledge.loader import ProcessedRecord


def _record(
    *,
    stem: str,
    mtime: float = 1.0,
    size: int = 100,
) -> ProcessedRecord:
    target = f"data/processed/iphone/logan/p1/note/{stem}.md"
    metadata = Metadata(
        product="logan",
        project="logan",
        build="p1",
        document_type="engineering_note",
        title=stem,
        source_file=f"data/raw/iphone/logan/p1/note/{stem}.md",
        target_file=target,
        source_mtime=mtime,
        source_size=size,
    )
    return ProcessedRecord(
        chunk_id=stem,
        content=f"# {stem}\n",
        metadata=metadata,
        target_file=target,
    )


def test_record_fingerprint_uses_source_fields() -> None:
    record = _record(stem="alpha", mtime=42.5, size=99)
    assert record_fingerprint(record) == {"source_mtime": 42.5, "source_size": 99}


def test_fingerprints_match_when_unchanged() -> None:
    record = _record(stem="alpha", mtime=42.5, size=99)
    stored = {"source_mtime": 42.5, "source_size": 99}
    assert fingerprints_match(stored, record)


def test_fingerprints_mismatch_on_size_change() -> None:
    record = _record(stem="alpha", mtime=42.5, size=100)
    stored = {"source_mtime": 42.5, "source_size": 99}
    assert not fingerprints_match(stored, record)


def test_plan_index_update_detects_new_changed_and_removed() -> None:
    alpha = _record(stem="alpha", mtime=1.0, size=10)
    manifest = IndexManifest(
        version=1,
        built_at="2026-01-01T00:00:00+00:00",
        chunk_count=2,
        source_fingerprints={
            alpha.target_file: record_fingerprint(alpha),
            "data/processed/iphone/logan/p1/note/removed.md": {
                "source_mtime": 3.0,
                "source_size": 30,
            },
        },
    )
    changed_beta = _record(stem="beta", mtime=2.0, size=21)
    gamma = _record(stem="gamma", mtime=4.0, size=40)
    records = [alpha, changed_beta, gamma]

    to_index, unchanged, removed = plan_index_update(records, manifest)

    assert unchanged == {alpha.target_file}
    assert {record.target_file for record in to_index} == {
        changed_beta.target_file,
        gamma.target_file,
    }
    assert removed == {"data/processed/iphone/logan/p1/note/removed.md"}


def test_plan_index_update_force_reindexes_all() -> None:
    alpha = _record(stem="alpha")
    manifest = IndexManifest(
        version=1,
        built_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
        source_fingerprints={alpha.target_file: record_fingerprint(alpha)},
    )
    to_index, unchanged, removed = plan_index_update([alpha], manifest, force=True)
    assert to_index == [alpha]
    assert unchanged == set()
    assert removed == set()
