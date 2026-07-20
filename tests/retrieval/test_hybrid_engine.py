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
    product: str = "iphone",
    project: str = "logan",
    build: str = "p1",
    document_type: str = "engineering_note",
) -> Chunk:
    metadata = Metadata(
        product=product,
        project=project,
        build=build,
        document_type=document_type,
        title=chunk_id,
        source_file=f"data/raw/{product}/{project}/{build}/note/{chunk_id}.md",
        target_file=f"data/processed/{product}/{project}/{build}/note/{chunk_id}.md",
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
            "product": chunk.metadata.product,
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
        product="global",
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
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        document_type="schematic",
    )
    assert len(results.chunks) == 1
    assert results.chunks[0].chunk_id == "sch__rmii"


def test_retrieve_scope_includes_common_and_global(engine_with_index) -> None:
    engine_with_index._embed_model.encode.return_value = np.array(
        [0.5, 0.5, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.2, 0.1, 0.9, 0.3])

    results = engine_with_index.retrieve(
        "UART debug",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
    )
    chunk_ids = {chunk.chunk_id for chunk in results.chunks}
    assert "common__sop" in chunk_ids


def test_retrieve_returns_empty_when_document_type_has_no_matches(engine_with_index) -> None:
    results = engine_with_index.retrieve(
        "RMII",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        document_type="sop",
    )
    assert results.chunks == []


def test_retrieve_pin_query_does_not_auto_filter_document_type(engine_with_index) -> None:
    """Pin wording must not hard-limit retrieval to schematic only (AGENTS.md)."""
    engine_with_index._embed_model.encode.return_value = np.array(
        [1.0, 0.0, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.95, 0.1, 0.2, 0.3])

    results = engine_with_index.retrieve(
        "VBAT pin power",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
    )
    assert results.chunks
    assert results.chunks[0].chunk_id == "note__power"


def test_retrieve_lcd_pin_query_prefers_build_schematic(engine_with_index) -> None:
    lcd_chunk = _make_chunk(
        "sch__lcd",
        "LCD module uses T_CS T_MOSI T_MISO T_SCK T_PEN touch pins.",
        document_type="schematic",
    )
    embeddings = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.5, 0.5, 0.0],
            [0.0, 0.0, 1.0],
            [0.2, 0.8, 0.0],
        ],
        dtype=np.float32,
    )
    chunks = [
        _make_chunk("note__power", "VBAT power rail connects to PMIC."),
        _make_chunk(
            "sch__rmii",
            "RMII interface connects ETH_MDIO and PHY.",
            document_type="schematic",
        ),
        _make_chunk("common__sop", "Bring-up SOP for UART debug.", build="common"),
        _make_chunk(
            "global__datasheet",
            "TPS62840 datasheet excerpt.",
            product="global",
            project="global",
            build="global",
            document_type="datasheet",
        ),
        lcd_chunk,
    ]
    engine_with_index.knowledge_base = [
        _hybrid_from_chunk(chunk, embeddings[index])
        for index, chunk in enumerate(chunks)
    ]
    engine_with_index._chunk_positions = {
        chunk.chunk_id: index for index, chunk in enumerate(engine_with_index.knowledge_base)
    }
    engine_with_index.bm25.get_scores.return_value = [0.1, 0.2, 0.3, 0.95, 0.4]
    engine_with_index._embed_model.encode.return_value = np.array(
        [0.0, 0.0, 1.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.2, 0.1, 0.3, 0.95, 0.5])

    results = engine_with_index.retrieve(
        "lcd的pin有哪些",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        top_k_final=1,
    )
    assert len(results.chunks) == 1
    assert results.chunks[0].chunk_id == "sch__lcd"


def test_retrieve_scope_ranks_override_filters_inherit_product(
    engine_with_index,
) -> None:
    scope_ranks = {
        ("iphone", "logan", "p1"): 0,
        ("iphone", "logan", "common"): 1,
        ("global", "global", "global"): 2,
    }
    engine_with_index._embed_model.encode.return_value = np.array(
        [0.5, 0.5, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.3, 0.2, 0.9, 0.1])

    results = engine_with_index.retrieve(
        "UART debug",
        target_product="iphone",
        target_project="logan",
        target_build=None,
        scope_ranks_override=scope_ranks,
        top_k_final=4,
    )
    chunk_ids = {chunk.chunk_id for chunk in results.chunks}
    assert "note__power" in chunk_ids
    assert "common__sop" in chunk_ids
    assert "global__datasheet" in chunk_ids


def test_retrieve_scope_rank_prefers_build_over_higher_rerank_common(
    engine_with_index,
) -> None:
    """Build-specific chunks outrank common even when reranker scores common higher."""
    engine_with_index._embed_model.encode.return_value = np.array(
        [0.5, 0.5, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.3, 0.2, 0.95, 0.1])

    results = engine_with_index.retrieve(
        "debug power UART",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        top_k_final=1,
    )
    assert len(results.chunks) == 1
    assert results.chunks[0].metadata.get("build") == "p1"


def test_retrieve_returns_empty_when_below_min_rerank_score(
    engine_with_index,
) -> None:
    from dataclasses import replace

    engine_with_index.config = replace(
        engine_with_index.config,
        retrieval=replace(engine_with_index.config.retrieval, min_rerank_score=10.0),
    )
    results = engine_with_index.retrieve(
        "UART debug",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
    )
    assert results.chunks == []
    assert results.top_rerank_score is not None
    assert results.top_rerank_score < 10.0


def test_cascade_build_sufficient_limits_global_primary(engine_with_index) -> None:
    """When build tier meets rerank threshold, global chunks are not primary."""
    engine_with_index._embed_model.encode.return_value = np.array(
        [1.0, 0.0, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.5, 0.2, 0.1, 0.95])

    results = engine_with_index.retrieve(
        "reset module",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        top_k_final=2,
    )
    assert len(results.chunks) == 2
    assert all(chunk.metadata.get("build") == "p1" for chunk in results.chunks)


def test_cascade_build_insufficient_falls_back_to_common(engine_with_index) -> None:
    from dataclasses import replace

    engine_with_index.config = replace(
        engine_with_index.config,
        retrieval=replace(
            engine_with_index.config.retrieval,
            scope_sufficient_rerank=0.5,
        ),
    )
    engine_with_index._embed_model.encode.return_value = np.array(
        [0.5, 0.5, 0.0], dtype=np.float32
    )
    score_by_id = {
        "note__power": 0.1,
        "sch__rmii": 0.2,
        "common__sop": 0.95,
        "global__datasheet": 0.05,
    }

    def _rerank_by_chunk_id(
        combined: list[HybridChunk],
        search_query: str,
    ) -> np.ndarray:
        _ = search_query
        return np.array([score_by_id[chunk.chunk_id] for chunk in combined], dtype=np.float32)

    engine_with_index._rerank_logits = _rerank_by_chunk_id

    results = engine_with_index.retrieve(
        "UART debug",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        top_k_final=1,
    )
    assert len(results.chunks) == 1
    assert results.chunks[0].chunk_id == "common__sop"


def test_cascade_mixed_quota_supplements_common_when_build_partial(engine_with_index) -> None:
    engine_with_index._embed_model.encode.return_value = np.array(
        [1.0, 0.0, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.8, 0.2, 0.7, 0.1])

    results = engine_with_index.retrieve(
        "power debug",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        top_k_final=4,
    )
    chunk_ids = [chunk.chunk_id for chunk in results.chunks]
    assert chunk_ids[0] in {"note__power", "sch__rmii"}
    assert "common__sop" in chunk_ids
    build_count = sum(1 for chunk in results.chunks if chunk.metadata.get("build") == "p1")
    assert build_count >= 2


def test_scope_inheritance_false_skips_cascade(engine_with_index) -> None:
    from dataclasses import replace

    engine_with_index.config = replace(
        engine_with_index.config,
        retrieval=replace(
            engine_with_index.config.retrieval,
            scope_inheritance=False,
        ),
    )
    engine_with_index._embed_model.encode.return_value = np.array(
        [0.5, 0.5, 0.0], dtype=np.float32
    )
    _mock_rerank_logits(engine_with_index._rerank_model, [0.3, 0.2, 0.95, 0.1])

    results = engine_with_index.retrieve(
        "UART debug",
        target_product="iphone",
        target_project="logan",
        target_build="p1",
        top_k_final=4,
    )
    chunk_ids = {chunk.chunk_id for chunk in results.chunks}
    assert "common__sop" not in chunk_ids
    assert "global__datasheet" not in chunk_ids
