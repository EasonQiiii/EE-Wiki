"""Tests for incremental index builds."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from ee_wiki.common.config import AppConfig
from ee_wiki.knowledge.indexer.build import build_index_from_processed
from ee_wiki.knowledge.indexer.store import load_index


def _write_processed(
    processed_dir: Path,
    stem: str,
    content: str,
    *,
    mtime: float,
    size: int,
) -> None:
    rel = Path("logan/p1/note") / f"{stem}.md"
    path = processed_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    target = f"data/processed/{rel.as_posix()}"
    meta = {
        "project": "logan",
        "build": "p1",
        "document_type": "engineering_note",
        "title": stem,
        "source_file": f"data/raw/{rel.as_posix()}",
        "target_file": target,
        "source_mtime": mtime,
        "source_size": size,
    }
    path.with_suffix(".md.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False),
        encoding="utf-8",
    )


def _mock_embedder(texts: list[str]) -> np.ndarray:
    return np.array([[float(len(text)), 0.5] for text in texts], dtype=np.float32)


def _test_config(app_config: AppConfig, tmp_path: Path) -> AppConfig:
    processed_dir = tmp_path / "processed"
    indexes_dir = tmp_path / "indexes"
    processed_dir.mkdir()
    indexes_dir.mkdir()
    return replace(
        app_config,
        processed_dir=processed_dir,
        indexes_dir=indexes_dir,
    )


def test_incremental_index_skips_unchanged_documents(app_config: AppConfig, tmp_path: Path) -> None:
    config = _test_config(app_config, tmp_path)
    _write_processed(
        config.processed_dir,
        "alpha",
        "# Alpha\n\nAlpha body.\n",
        mtime=1.0,
        size=10,
    )
    _write_processed(
        config.processed_dir,
        "beta",
        "# Beta\n\nBeta body.\n",
        mtime=2.0,
        size=20,
    )

    first = build_index_from_processed(config, embedder=_mock_embedder)
    assert first.chunk_count == 2
    assert first.indexed_documents == 2

    second = build_index_from_processed(config, embedder=_mock_embedder)
    assert second.chunk_count == 2
    assert second.indexed_documents == 0
    assert second.skipped_documents == 2
    assert second.removed_documents == 0


def test_incremental_index_updates_changed_document(app_config: AppConfig, tmp_path: Path) -> None:
    config = _test_config(app_config, tmp_path)
    _write_processed(
        config.processed_dir,
        "alpha",
        "# Alpha\n\nAlpha body.\n",
        mtime=1.0,
        size=10,
    )
    build_index_from_processed(config, embedder=_mock_embedder)
    loaded_before = load_index(config.indexes_dir)
    alpha_vector = loaded_before.embeddings[0].copy()

    _write_processed(
        config.processed_dir,
        "alpha",
        "# Alpha\n\nAlpha body changed.\n",
        mtime=1.5,
        size=11,
    )
    result = build_index_from_processed(config, embedder=_mock_embedder)
    assert result.indexed_documents == 1
    assert result.skipped_documents == 0

    loaded_after = load_index(config.indexes_dir)
    assert loaded_after.embeddings.shape[0] == 1
    assert not np.array_equal(loaded_after.embeddings[0], alpha_vector)
    assert "changed" in loaded_after.chunks[0].content


def test_incremental_index_removes_deleted_document(app_config: AppConfig, tmp_path: Path) -> None:
    config = _test_config(app_config, tmp_path)
    _write_processed(
        config.processed_dir,
        "alpha",
        "# Alpha\n\nAlpha body.\n",
        mtime=1.0,
        size=10,
    )
    _write_processed(
        config.processed_dir,
        "beta",
        "# Beta\n\nBeta body.\n",
        mtime=2.0,
        size=20,
    )
    build_index_from_processed(config, embedder=_mock_embedder)

    beta_path = config.processed_dir / "logan/p1/note/beta.md"
    beta_meta = beta_path.with_suffix(".md.meta.json")
    beta_path.unlink()
    beta_meta.unlink()

    result = build_index_from_processed(config, embedder=_mock_embedder)
    assert result.removed_documents == 1
    assert result.indexed_documents == 0
    assert result.skipped_documents == 1
    assert result.chunk_count == 1

    loaded = load_index(config.indexes_dir)
    assert len(loaded.chunks) == 1
    assert loaded.chunks[0].chunk_id == "alpha__alpha"


def test_force_rebuild_reindexes_everything(app_config: AppConfig, tmp_path: Path) -> None:
    config = _test_config(app_config, tmp_path)
    _write_processed(
        config.processed_dir,
        "alpha",
        "# Alpha\n\nAlpha body.\n",
        mtime=1.0,
        size=10,
    )
    build_index_from_processed(config, embedder=_mock_embedder)

    result = build_index_from_processed(config, force=True, embedder=_mock_embedder)
    assert result.indexed_documents == 1
    assert result.skipped_documents == 0
