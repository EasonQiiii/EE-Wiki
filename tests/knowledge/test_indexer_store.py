"""Tests for on-disk index persistence."""

from __future__ import annotations

import numpy as np
import pytest

from ee_wiki.common.types import Chunk, Citation, Metadata
from ee_wiki.knowledge.indexer.component_index import COMPONENTS_NAME, save_component_index
from ee_wiki.knowledge.indexer.store import (
    IndexStoreError,
    clear_index,
    index_exists,
    load_index,
    save_index,
)


def _sample_chunk(chunk_id: str, content: str) -> Chunk:
    metadata = Metadata(
        project="logan",
        build="p1",
        document_type="engineering_note",
        title="manual",
        source_file="data/raw/logan/p1/note/manual.md",
        target_file="data/processed/logan/p1/note/manual.md",
    )
    return Chunk(
        chunk_id=chunk_id,
        content=content,
        metadata=metadata,
        citation=Citation(
            source_file=metadata.source_file,
            chunk_id=chunk_id,
            excerpt=content[:80],
        ),
    )


def test_save_and_load_index_roundtrip(tmp_path) -> None:
    chunks = [
        _sample_chunk("manual__power", "VBAT connects to U0902."),
        _sample_chunk("manual__debug", "UART debug notes."),
    ]
    embeddings = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    bm25_corpus = [["vbat", "u0902"], ["uart", "debug"]]
    fingerprints = {
        "data/processed/logan/p1/note/manual.md": {
            "source_mtime": 1.0,
            "source_size": 42,
        }
    }

    manifest = save_index(
        tmp_path,
        chunks=chunks,
        embeddings=embeddings,
        bm25_corpus=bm25_corpus,
        source_fingerprints=fingerprints,
    )
    assert manifest.chunk_count == 2
    assert index_exists(tmp_path)

    loaded = load_index(tmp_path)
    assert len(loaded.chunks) == 2
    assert loaded.chunks[0].chunk_id == "manual__power"
    assert loaded.embeddings.shape == (2, 2)
    assert loaded.bm25_corpus[1] == ["uart", "debug"]
    assert loaded.manifest.source_fingerprints == fingerprints


def test_save_index_rejects_mismatched_counts(tmp_path) -> None:
    chunks = [_sample_chunk("only", "content")]
    embeddings = np.zeros((2, 4), dtype=np.float32)
    with pytest.raises(IndexStoreError, match="does not match"):
        save_index(
            tmp_path,
            chunks=chunks,
            embeddings=embeddings,
            bm25_corpus=[["a"]],
            source_fingerprints={},
        )


def test_clear_index_removes_all_artifacts(tmp_path) -> None:
    chunks = [_sample_chunk("manual__power", "VBAT connects to U0902.")]
    embeddings = np.array([[1.0, 0.0]], dtype=np.float32)
    save_index(
        tmp_path,
        chunks=chunks,
        embeddings=embeddings,
        bm25_corpus=[["vbat"]],
        source_fingerprints={
            "data/processed/logan/p1/note/manual.md": {
                "source_mtime": 1.0,
                "source_size": 42,
            }
        },
    )
    save_component_index(chunks, tmp_path)

    removed = clear_index(tmp_path)
    assert removed == 1
    assert not index_exists(tmp_path)
    assert not (tmp_path / COMPONENTS_NAME).is_file()


def test_clear_index_on_missing_index_returns_zero(tmp_path) -> None:
    assert clear_index(tmp_path) == 0
