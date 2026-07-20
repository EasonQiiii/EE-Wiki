"""Tests for generation context formatting."""

from __future__ import annotations

from ee_wiki.generation.context import (
    chunks_to_citations,
    format_context_blocks,
    format_history_block,
    knowledge_scope_tier,
    resolve_history_for_prompt,
)
from ee_wiki.retrieval.hybrid.engine import HybridChunk
from ee_wiki.retrieval.rewrite import ConversationTurn


def test_knowledge_scope_tier() -> None:
    assert knowledge_scope_tier("global", "global", "global") == "global"
    assert knowledge_scope_tier("iphone", "common", "common") == "product_common"
    assert knowledge_scope_tier("iphone", "logan", "common") == "project_common"
    assert knowledge_scope_tier("iphone", "logan", "p1") == "build"


def test_format_context_blocks_numbers_chunks_and_scope() -> None:
    chunks = [
        HybridChunk(
            chunk_id="a__1",
            content="First chunk body.",
            metadata={
                "product": "iphone",
                "project": "logan",
                "build": "p1",
                "document_type": "engineering_note",
            },
            citation={
                "source_file": "data/raw/iphone/logan/p1/note/a.md",
                "chunk_id": "a__1",
                "page": 0,
                "excerpt": "First",
            },
        ),
        HybridChunk(
            chunk_id="common__sop",
            content="Project bring-up SOP.",
            metadata={
                "product": "iphone",
                "project": "logan",
                "build": "common",
                "document_type": "sop",
            },
            citation={
                "source_file": "data/raw/iphone/logan/common/sop/bringup.md",
                "chunk_id": "common__sop",
                "page": 0,
                "excerpt": "SOP",
            },
        ),
        HybridChunk(
            chunk_id="ds__lan",
            content="Generic PHY datasheet excerpt.",
            metadata={
                "product": "global",
                "project": "global",
                "build": "global",
                "document_type": "datasheet",
            },
            citation={
                "source_file": "data/raw/global/datasheet/LAN8720A.pdf",
                "chunk_id": "ds__lan",
                "page": 1,
                "excerpt": "RMII",
            },
        ),
    ]

    rendered = format_context_blocks(chunks)
    assert "[1] scope=build product=iphone project=logan build=p1" in rendered
    assert "First chunk body." in rendered
    assert (
        "[2] scope=project_common product=iphone project=logan build=common"
        in rendered
    )
    assert "[3] scope=global product=global project=global build=global" in rendered
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


def test_resolve_history_for_prompt_omits_unrelated_turns() -> None:
    history = [
        ConversationTurn(role="user", content="topic A"),
        ConversationTurn(role="assistant", content="answer A"),
    ]
    rendered = resolve_history_for_prompt(
        "What is the maximum voltage for TPS2514A on Logan P1?",
        history,
    )
    assert rendered == "(none)"


def test_resolve_history_for_prompt_keeps_semantic_translate_follow_up() -> None:
    history = [
        ConversationTurn(role="user", content="topic A"),
        ConversationTurn(role="assistant", content="answer A"),
    ]
    rendered = resolve_history_for_prompt(
        "Please render the previous answer in English for the team.",
        history,
        prepared_task="translate",
    )
    assert "answer A" in rendered


def test_resolve_history_for_prompt_keeps_short_follow_up_turns() -> None:
    history = [
        ConversationTurn(role="user", content="topic A"),
        ConversationTurn(role="assistant", content="answer A"),
    ]
    rendered = resolve_history_for_prompt("用英文", history)
    assert "answer A" in rendered


def test_format_history_block_empty_returns_placeholder() -> None:
    assert format_history_block(None) == "(none)"
    assert format_history_block([]) == "(none)"


def test_format_history_block_keeps_recent_turns_verbatim() -> None:
    history = [
        ConversationTurn(role="user", content="ipad快速放电指令"),
        ConversationTurn(role="assistant", content="方案 A：diagstool hwmisc --displayPower=1 [1]"),
    ]
    rendered = format_history_block(history)
    assert "[User]:\nipad快速放电指令" in rendered
    assert "[Assistant]:\n方案 A：diagstool hwmisc --displayPower=1 [1]" in rendered


def test_format_history_block_truncates_long_turns_and_limits_count() -> None:
    history = [
        ConversationTurn(role="user", content=f"question {i}") for i in range(10)
    ] + [ConversationTurn(role="assistant", content="x" * 5000)]
    rendered = format_history_block(history, max_turns=3, max_chars_per_turn=100)
    assert "question 7" not in rendered
    assert "question 8" in rendered
    assert "question 9" in rendered
    assert "…(truncated)" in rendered
    assert "x" * 101 not in rendered


def test_chunks_to_citations_maps_fields() -> None:
    chunks = [
        HybridChunk(
            chunk_id="sch__rmii",
            content="RMII notes",
            metadata={},
            citation={
                "source_file": "data/raw/iphone/logan/p1/sch/board.pdf",
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
