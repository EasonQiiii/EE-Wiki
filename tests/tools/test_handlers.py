"""Tests for engineering tool handlers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ee_wiki.common.config import AppConfig
from ee_wiki.knowledge.indexer.component_index import ComponentHit
from ee_wiki.retrieval.hybrid.engine import HybridChunk, RetrievalResult
from ee_wiki.tools.context import ToolContext
from ee_wiki.tools.handlers import (
    engineering_search,
    graph_neighbors,
    query_schematic,
    search_component,
    search_datasheet,
)


def _ctx(app_config: AppConfig) -> ToolContext:
    engine = MagicMock()
    return ToolContext(config=app_config, engine=engine)


def _component_hit() -> ComponentHit:
    return ComponentHit(
        key="U101",
        kind="designator",
        chunk_id="board__p001",
        project="logan",
        build="p1",
        document_type="schematic",
        source_file="data/raw/logan/p1/sch/board.pdf",
        page=1,
        title="board",
        excerpt="U101 PHY",
    )


def _hybrid_chunk(
    *,
    document_type: str = "schematic",
    project: str = "logan",
    build: str = "p1",
) -> HybridChunk:
    return HybridChunk(
        chunk_id="board__p001",
        content="U101 connects RMII signals.",
        metadata={
            "project": project,
            "build": build,
            "document_type": document_type,
            "title": "board",
        },
        citation={
            "source_file": "data/raw/logan/p1/sch/board.pdf",
            "chunk_id": "board__p001",
            "page": 1,
            "excerpt": "U101 connects RMII signals.",
        },
    )


def test_search_component_returns_json_hits(app_config: AppConfig) -> None:
    ctx = _ctx(app_config)
    ctx.engine.search_components.return_value = [_component_hit()]

    payload = json.loads(
        search_component(ctx, "U101", project="logan", build="p1", limit=5)
    )

    assert payload["query"] == "U101"
    assert len(payload["hits"]) == 1
    assert payload["hits"][0]["scope"] == "build"
    ctx.engine.search_components.assert_called_once_with(
        "U101",
        target_project="logan",
        target_build="p1",
        limit=5,
    )


def test_query_schematic_filters_document_type(app_config: AppConfig) -> None:
    ctx = _ctx(app_config)
    ctx.engine.retrieve.return_value = RetrievalResult(
        chunks=[_hybrid_chunk()],
        top_rerank_score=-1.5,
    )

    payload = json.loads(query_schematic(ctx, "RMII 连接", project="logan", build="p1"))

    assert payload["document_type"] == "schematic"
    assert payload["hits"][0]["document_type"] == "schematic"
    ctx.engine.retrieve.assert_called_once_with(
        "RMII 连接",
        target_project="logan",
        target_build="p1",
        document_type="schematic",
        top_k_final=None,
    )


def test_search_datasheet_filters_document_type(app_config: AppConfig) -> None:
    ctx = _ctx(app_config)
    ctx.engine.retrieve.return_value = RetrievalResult(
        chunks=[_hybrid_chunk(document_type="datasheet", project="global", build="global")],
        top_rerank_score=-0.5,
    )

    payload = json.loads(search_datasheet(ctx, "168 MHz", project="global", build="global"))

    assert payload["document_type"] == "datasheet"
    assert payload["hits"][0]["scope"] == "global"
    ctx.engine.retrieve.assert_called_once_with(
        "168 MHz",
        target_project="global",
        target_build="global",
        document_type="datasheet",
        top_k_final=None,
    )


def test_engineering_search_allows_optional_document_type(app_config: AppConfig) -> None:
    ctx = _ctx(app_config)
    ctx.engine.retrieve.return_value = RetrievalResult(chunks=[], top_rerank_score=None)

    payload = json.loads(
        engineering_search(
            ctx,
            "bring-up checklist",
            project="logan",
            build="common",
            document_type="sop",
            top_k=3,
        )
    )

    assert payload["document_type"] == "sop"
    assert payload["hits"] == []
    ctx.engine.retrieve.assert_called_once_with(
        "bring-up checklist",
        target_project="logan",
        target_build="common",
        document_type="sop",
        top_k_final=3,
    )


def test_graph_neighbors_reports_missing_graph(
    app_config: AppConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP graph tools return a JSON error when the graph bundle is absent."""
    monkeypatch.setattr(
        "ee_wiki.tools.handlers.graph_exists",
        lambda _path: False,
    )
    ctx = _ctx(app_config)
    payload = json.loads(graph_neighbors(ctx, "U101", project="logan", build="p1"))
    assert "error" in payload
    assert "Knowledge graph not found" in payload["error"]
