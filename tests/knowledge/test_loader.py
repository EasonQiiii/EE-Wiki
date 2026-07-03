"""Tests for processed mirror loading."""

from __future__ import annotations

import json
from pathlib import Path

from ee_wiki.knowledge.loader import load_processed_records
from ee_wiki.retrieval.processed_loader import (
    ProcessedRecord,
)
from ee_wiki.retrieval.processed_loader import (
    load_processed_records as reexport_load,
)


def test_load_processed_records_reads_md_and_sidecar(tmp_path: Path) -> None:
    doc_dir = tmp_path / "logan" / "p1" / "note"
    doc_dir.mkdir(parents=True)
    md_path = doc_dir / "sample.md"
    md_path.write_text("# Sample\n\nBody text.\n", encoding="utf-8")
    meta_path = doc_dir / "sample.md.meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "project": "logan",
                "build": "p1",
                "document_type": "engineering_note",
                "title": "sample",
                "source_file": "data/raw/logan/p1/note/sample.md",
                "target_file": "data/processed/logan/p1/note/sample.md",
            }
        ),
        encoding="utf-8",
    )

    records = load_processed_records(tmp_path)
    assert len(records) == 1
    record = records[0]
    assert record.chunk_id == "sample"
    assert "Body text" in record.content
    assert record.metadata.project == "logan"
    assert record.metadata.build == "p1"
    assert record.target_file == "data/processed/logan/p1/note/sample.md"


def test_processed_loader_reexport_matches_knowledge_loader(tmp_path: Path) -> None:
    doc_dir = tmp_path / "global" / "global" / "note"
    doc_dir.mkdir(parents=True)
    (doc_dir / "faq.md").write_text("FAQ content\n", encoding="utf-8")

    records = reexport_load(tmp_path)
    assert len(records) == 1
    assert isinstance(records[0], ProcessedRecord)
    assert records[0].chunk_id == "faq"
