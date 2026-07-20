"""End-to-end tests for raw deletion → processed cleanup → index removal."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.ingestion.pipeline import ingest_path
from ee_wiki.knowledge.indexer.build import build_index_from_processed
from ee_wiki.knowledge.indexer.store import index_exists, load_index


@pytest.fixture
def sync_config(app_config: AppConfig, tmp_path: Path) -> AppConfig:
    raw_dir = tmp_path / "raw"
    processed_dir = tmp_path / "processed"
    indexes_dir = tmp_path / "indexes"
    raw_dir.mkdir()
    processed_dir.mkdir()
    indexes_dir.mkdir()
    layout = replace(
        app_config.data_layout,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )
    return replace(
        app_config,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        indexes_dir=indexes_dir,
        data_layout=layout,
    )


def _mock_embedder(texts: list[str]) -> np.ndarray:
    return np.array([[float(len(text)), 0.5] for text in texts], dtype=np.float32)


def test_raw_delete_flows_through_ingest_and_index(sync_config: AppConfig) -> None:
    alpha_raw = sync_config.raw_dir / "iphone/logan/p1/note/alpha.md"
    beta_raw = sync_config.raw_dir / "iphone/logan/p1/note/beta.md"
    alpha_raw.parent.mkdir(parents=True)
    alpha_raw.write_text("# Alpha\n\nAlpha body.\n", encoding="utf-8")
    beta_raw.write_text("# Beta\n\nBeta body.\n", encoding="utf-8")

    ingest_path(sync_config.raw_dir, sync_config)
    build_index_from_processed(sync_config, embedder=_mock_embedder)
    assert load_index(sync_config.indexes_dir).manifest.chunk_count == 2

    beta_raw.unlink()
    ingest_run = ingest_path(sync_config.raw_dir, sync_config)
    assert len(ingest_run.removed) == 1
    assert not (sync_config.processed_dir / "iphone/logan/p1/note/beta.md").is_file()

    index_run = build_index_from_processed(sync_config, embedder=_mock_embedder)
    assert index_run.removed_documents == 1
    assert index_run.chunk_count == 1
    assert load_index(sync_config.indexes_dir).manifest.chunk_count == 1

    alpha_raw.unlink()
    ingest_path(sync_config.raw_dir, sync_config)
    final_index = build_index_from_processed(sync_config, embedder=_mock_embedder)
    assert final_index.removed_documents == 1
    assert final_index.chunk_count == 0
    assert not index_exists(sync_config.indexes_dir)
