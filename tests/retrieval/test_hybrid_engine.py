"""Tests for hybrid retrieval engine."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from ee_wiki.common.types import Chunk, Citation, Metadata
from ee_wiki.retrieval.hybrid.engine import HybridChunk, HybridRagEngine


def _make_chunk(
    chunk_id: str,
    content: str,
    *,
    project: str = "logan",
    build: str = "p1",
    document_type: str = "engineering_note",
) -> Chunk:
    metadata = Metadata(
        project=project,
        build=build,
        document_type=document_type,
        title=chunk_id,
        source_file=f"data/raw/{project}/{build}/note/{chunk_id}.md",
        target_file=f"data/processed/{project}/{build}/note/{chunk_id}.md",
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


def _hybrid_from_chunk(chunk: Chunk, embedding: np.ndarray) -> HybridChunk:
    return HybridChunk(
        chunk_id=chunk.chunk_id,
        content=chunk.content,
        metadata={
            "project": chunk.metadata.project,
            "build": chunk.metadata.build,
            "document_type": chunk.metadata.document_type,
        },
        citation={
            "source_file": chunk.citation.source_file,
            "chunk_id": chunk.citation.chunk_id,
            "page": chunk.citation.page,
            "excerpt": chunk.citation.excerpt,
        },
        embedding=embedding,
    )


def _mock_rerank_logits(model: MagicMock, values: list[float]) -> None:
    logits = model.return_value.logits.view.return_value.float.return_value.cpu.return_value.numpy
    logits.return_value = np.array(values)


@pytest.fixture
def engine_with_index(app_config):
    note_chunk = _make_chunk("note__power", "VBAT power rail connects to PMIC.")
    sch_chunk = _make_chunk(
        "sch__rmii",
        "RMII interface connects ETH_MDIO and PHY.",
        document_type="schematic",
    )
    common_chunk = _make_chunk(
        "common__sop",
        "Bring-up SOP for UART debug.",
        build="common",
    )
    global_chunk = _make_chunk(
        "global__datasheet",
        "TPS62840 datasheet excerpt.",
        project="global",
        build="global",
        document_type="datasheet",
    )

    chunks = [note_chunk, sch_chunk, common_chunk, global_chunk]
    embeddings = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.5, 0.5, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )

    engine = HybridRagEngine(app_config)
    engine.knowledge_base = [
        _hybrid_from_chunk(chunk, embeddings[index])
        for index, chunk in enumerate(chunks)
    ]
    engine._chunk_positions = {
        chunk.chunk_id: index for index, chunk in enumerate(engine.knowledge_base)
    }
    engine.bm25 = MagicMock()
    engine.bm25.get_scores.return_value = [0.1, 0.9, 0.5, 0.2]

    mock_embed = MagicMock()
    mock_embed.encode.return_value = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    engine._embed_model = mock_embed

    mock_reranker = MagicMock()
    _mock_rerank_logits(mock_reranker, [0.1, 0.9, 0.2, 0.3])
    tokenizer_batch = {"input_ids": MagicMock(), "attention_mask": MagicMock()}
    tokenizer_output = MagicMock()
    tokenizer_output.to.return_value = tokenizer_batch
    engine._rerank_tokenizer = MagicMock(return_value=tokenizer_output)
    engine._rerank_model = mock_reranker

    return engine


def test_retrieve_filters_by_document_type(engine_with_index) -> None:
    results = engine_with_index.retrieve(
        "RMII",
        target_project="logan",
        target_build="p1",
        document_type="schematic",
    )
    assert len(results) == 1
    assert results[0].chunk_id == "sch__rmii"


def test_retrieve_scope_includes_common_and_global(engine_with_index) -> None:
    engine_with_index._embed_model.encode.return_value = np.array(
        [0.5, 0.5, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.2, 0.1, 0.9, 0.3])

    results = engine_with_index.retrieve(
        "UART debug",
        target_project="logan",
        target_build="p1",
    )
    chunk_ids = {chunk.chunk_id for chunk in results}
    assert "common__sop" in chunk_ids


def test_retrieve_returns_empty_when_document_type_has_no_matches(engine_with_index) -> None:
    results = engine_with_index.retrieve(
        "RMII",
        target_project="logan",
        target_build="p1",
        document_type="sop",
    )
    assert results == []


def test_retrieve_pin_query_defaults_to_schematic_sources(engine_with_index) -> None:
    results = engine_with_index.retrieve(
        "proj_a build_b module_x pin signals",
        target_project="logan",
        target_build="p1",
    )
    assert results
    assert all(chunk.metadata.get("document_type") == "schematic" for chunk in results)
