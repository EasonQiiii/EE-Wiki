"""End-to-end smoke test: raw ingest → index → retrieve → RAG answer with citations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.generation.service import RagService
from ee_wiki.ingestion.pipeline import ingest_path
from ee_wiki.knowledge.indexer.build import build_index_from_processed
from ee_wiki.retrieval.hybrid.engine import HybridRagEngine


def _mock_embedder(texts: list[str]) -> np.ndarray:
    return np.array([[float(len(text)), 0.5] for text in texts], dtype=np.float32)


def _mock_rerank_logits(model: MagicMock, values: list[float]) -> None:
    logits = model.return_value.logits.view.return_value.float.return_value.cpu.return_value.numpy
    logits.return_value = np.array(values)


@pytest.fixture
def smoke_config(app_config: AppConfig, tmp_path: Path) -> AppConfig:
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


def _patch_engine_for_query(engine: HybridRagEngine) -> None:
    mock_embed = MagicMock()
    mock_embed.encode.return_value = np.array([37.0, 0.5], dtype=np.float32)
    engine._embed_model = mock_embed

    mock_reranker = MagicMock()
    _mock_rerank_logits(mock_reranker, [0.9])
    tokenizer_batch = {"input_ids": MagicMock(), "attention_mask": MagicMock()}
    tokenizer_output = MagicMock()
    tokenizer_output.to.return_value = tokenizer_batch
    engine._rerank_tokenizer = MagicMock(return_value=tokenizer_output)
    engine._rerank_model = mock_reranker


def test_rag_smoke_raw_to_answer_with_citation(smoke_config: AppConfig) -> None:
    raw_path = smoke_config.raw_dir / "logan/p1/note/power.md"
    raw_path.parent.mkdir(parents=True)
    raw_path.write_text(
        "# Power\n\nVBAT connects to PMIC U0902.\n",
        encoding="utf-8",
    )

    ingest_path(smoke_config.raw_dir, smoke_config)
    build_index_from_processed(smoke_config, embedder=_mock_embedder)

    engine = HybridRagEngine(smoke_config)
    engine.load_index()
    _patch_engine_for_query(engine)

    mock_llm = MagicMock()
    mock_llm.generate.return_value = "VBAT connects to PMIC U0902 [1]."

    service = RagService(config=smoke_config, engine=engine, llm=mock_llm)
    result = service.answer(
        "What is VBAT connected to?",
        target_project="logan",
        target_build="p1",
    )

    assert not result.insufficient_context
    assert len(result.citations) >= 1
    assert "data/raw/logan/p1/note/power.md" in result.citations[0].source_file
    assert "[1]" in result.answer

    prompt = mock_llm.generate.call_args.args[0]
    assert "VBAT connects to PMIC U0902." in prompt
    assert "What is VBAT connected to?" in prompt
