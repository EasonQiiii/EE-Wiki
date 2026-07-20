"""Tests for tool result formatting."""

from __future__ import annotations

import json

from ee_wiki.knowledge.indexer.component_index import ComponentHit
from ee_wiki.retrieval.hybrid.engine import HybridChunk, RetrievalResult
from ee_wiki.tools.format import format_component_search, format_retrieval_result


def test_format_component_search_includes_scope(app_config) -> None:
    hits = [
        ComponentHit(
            key="STM32F407VGT6",
            kind="part_number",
            chunk_id="stm32__p001",
            product="global",
            project="global",
            build="global",
            document_type="datasheet",
            source_file="data/raw/global/datasheet/STM32F407ZGT6.pdf",
            page=0,
            title="STM32F407ZGT6",
            excerpt="168 MHz",
        )
    ]

    payload = json.loads(
        format_component_search(query="STM32F407VGT6", hits=hits, layout=app_config.data_layout)
    )

    assert payload["hits"][0]["scope"] == "global"


def test_format_retrieval_result_truncates_content(app_config) -> None:
    result = RetrievalResult(
        chunks=[
            HybridChunk(
                chunk_id="board__p001",
                content="x" * 1200,
                metadata={
                    "product": "iphone",
                    "project": "logan",
                    "build": "p1",
                    "document_type": "schematic",
                    "title": "board",
                },
                citation={
                    "source_file": "data/raw/iphone/logan/p1/sch/board.pdf",
                    "chunk_id": "board__p001",
                    "page": 1,
                    "excerpt": "preview",
                },
            )
        ],
        top_rerank_score=-2.0,
    )

    payload = json.loads(
        format_retrieval_result(
            query="U101",
            result=result,
            layout=app_config.data_layout,
            document_type="schematic",
            content_preview_chars=100,
        )
    )

    assert payload["hits"][0]["content"].endswith("...")
    assert len(payload["hits"][0]["content"]) < 1200
