"""Tests for generation context formatting."""

from __future__ import annotations

from ee_wiki.generation.context import (
    chunks_to_citations,
    format_context_blocks,
    knowledge_scope_tier,
)
from ee_wiki.retrieval.hybrid.engine import HybridChunk


def test_knowledge_scope_tier() -> None:
    assert knowledge_scope_tier("global", "global") == "global"
    assert knowledge_scope_tier("logan", "common") == "project_common"
    assert knowledge_scope_tier("logan", "p1") == "build"


def test_format_context_blocks_numbers_chunks_and_scope() -> None:
    chunks = [
        HybridChunk(
            chunk_id="a__1",
            content="First chunk body.",
            metadata={"project": "logan", "build": "p1", "document_type": "engineering_note"},
            citation={
                "source_file": "data/raw/logan/p1/note/a.md",
                "chunk_id": "a__1",
                "page": 0,
                "excerpt": "First",
            },
        ),
        HybridChunk(
            chunk_id="common__sop",
            content="Project bring-up SOP.",
            metadata={"project": "logan", "build": "common", "document_type": "sop"},
            citation={
                "source_file": "data/raw/logan/common/sop/bringup.md",
                "chunk_id": "common__sop",
                "page": 0,
                "excerpt": "SOP",
            },
        ),
        HybridChunk(
            chunk_id="ds__lan",
            content="Generic PHY datasheet excerpt.",
            metadata={"project": "global", "build": "global", "document_type": "datasheet"},
            citation={
                "source_file": "data/raw/global/datasheet/LAN8720A.pdf",
                "chunk_id": "ds__lan",
                "page": 1,
                "excerpt": "RMII",
            },
        ),
    ]

    rendered = format_context_blocks(chunks)
    assert "[1] scope=build project=logan build=p1" in rendered
    assert "First chunk body." in rendered
    assert "[2] scope=project_common project=logan build=common" in rendered
    assert "[3] scope=global project=global build=global" in rendered
    assert "Generic PHY datasheet excerpt." in rendered


def test_format_context_blocks_includes_heading_path() -> None:
    chunks = [
        HybridChunk(
            chunk_id="ipadmanal__9-1",
            content="### 9.1 方案 A（基础）\n\ndiagstool hwmisc",
            metadata={"project": "global", "build": "global", "document_type": "engineering_note"},
            citation={
                "source_file": "data/raw/global/note/ipadmanal.md",
                "chunk_id": "ipadmanal__9-1",
                "page": 0,
                "excerpt": "diagstool",
            },
            heading_path="iPad 工程操作手册 › 9. 快速放电方案 › 9.1 方案 A（基础）",
        )
    ]

    rendered = format_context_blocks(chunks)
    assert "section=iPad 工程操作手册 › 9. 快速放电方案 › 9.1 方案 A（基础）" in rendered
    assert "diagstool hwmisc" in rendered


def test_chunks_to_citations_maps_fields() -> None:
    chunks = [
        HybridChunk(
            chunk_id="sch__rmii",
            content="RMII notes",
            metadata={},
            citation={
                "source_file": "data/raw/logan/p1/sch/board.pdf",
                "chunk_id": "sch__rmii",
                "page": 3,
                "excerpt": "RMII",
            },
        )
    ]
    citations = chunks_to_citations(chunks)
    assert len(citations) == 1
    assert citations[0].source_file.endswith("board.pdf")
    assert citations[0].chunk_id == "sch__rmii"
    assert citations[0].page == 3
