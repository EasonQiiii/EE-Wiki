"""Tests for RAG service orchestration."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from ee_wiki.generation.service import INSUFFICIENT_ANSWER, RagService
from ee_wiki.retrieval.hybrid.engine import HybridChunk, RetrievalResult
from ee_wiki.retrieval.rewrite import ConversationTurn


@pytest.fixture
def rag_service(app_config):
    config = replace(
        app_config,
        generation=replace(app_config.generation, assistant_fallback=False),
    )
    engine = MagicMock()
    llm = MagicMock()
    llm.generate_stream = None
    return RagService(config=config, engine=engine, llm=llm)


def test_answer_returns_insufficient_when_no_chunks(rag_service) -> None:
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[])
    result = rag_service.answer("unknown topic", target_project="logan", target_build="p1")
    assert result.insufficient_context is True
    assert result.answer == INSUFFICIENT_ANSWER
    assert result.citations == []
    rag_service.llm.generate.assert_not_called()


def test_answer_generates_from_retrieved_chunks(rag_service, repo_root) -> None:
    chunk = HybridChunk(
        chunk_id="note__power",
        content="VBAT connects to PMIC.",
        metadata={
            "project": "logan",
            "build": "p1",
            "document_type": "engineering_note",
            "title": "note",
            "target_file": "data/processed/logan/p1/note/note.md",
        },
        citation={
            "source_file": "data/raw/logan/p1/note/note.md",
            "chunk_id": "note__power",
            "page": 0,
            "excerpt": "VBAT",
        },
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[chunk], top_rerank_score=1.0)

    captured: dict[str, str] = {}

    def _fake_stream(prompt: str, cancel_event=None):
        captured["prompt"] = prompt
        yield "VBAT is connected to the PMIC [1]."

    rag_service.llm.generate_stream = _fake_stream

    result = rag_service.answer("What is VBAT?", target_project="logan", target_build="p1")
    assert result.insufficient_context is False
    assert "VBAT" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == "note__power"
    assert result.citations[0].url.endswith("/v1/sources/logan/p1/note/note.md#power")
    assert "[1]" in result.answer
    assert "<a href=" not in result.answer
    assert "**引用 / References**" not in result.answer
    rag_service.llm.generate.assert_not_called()
    assert "VBAT connects to PMIC." in captured["prompt"]
    assert "What is VBAT?" in captured["prompt"]


def test_answer_uses_debug_task_prompt(rag_service, repo_root) -> None:
    chunk = HybridChunk(
        chunk_id="note__power",
        content="UART debug on JTAG header.",
        metadata={
            "project": "logan",
            "build": "p1",
            "document_type": "engineering_note",
            "title": "note",
            "target_file": "data/processed/logan/p1/note/note.md",
        },
        citation={
            "source_file": "data/raw/logan/p1/note/note.md",
            "chunk_id": "note__power",
            "page": 0,
            "excerpt": "UART",
        },
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[chunk], top_rerank_score=1.0)

    captured: dict[str, str] = {}

    def _fake_stream(prompt: str, cancel_event=None):
        captured["prompt"] = prompt
        yield "Check UART wiring [1]."

    rag_service.llm.generate_stream = _fake_stream

    rag_service.answer(
        "Why is UART silent?",
        target_project="logan",
        target_build="p1",
        task="debug",
    )
    assert "hardware debug assistant" in captured["prompt"].lower()
    assert "UART debug on JTAG header." in captured["prompt"]


def test_stream_answer_yields_llm_fragments_directly(rag_service) -> None:
    chunk = HybridChunk(
        chunk_id="note__power",
        content="VBAT connects to PMIC.",
        metadata={"project": "logan", "build": "p1", "document_type": "engineering_note"},
        citation={"source_file": "data/raw/logan/p1/note/note.md", "chunk_id": "note__power"},
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[chunk], top_rerank_score=1.0)

    def _fake_stream(prompt: str, cancel_event=None):
        yield "VBAT "
        yield "answer."

    rag_service.llm.generate_stream = _fake_stream

    result = rag_service.stream_answer("What is VBAT?")
    assert "".join(result.text_chunks) == "VBAT answer."


def test_stream_answer_honours_cancel_before_generation(rag_service) -> None:
    import threading

    cancel = threading.Event()
    cancel.set()
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[])

    result = rag_service.stream_answer("ignored", cancel_event=cancel)
    assert list(result.text_chunks) == []
    rag_service.engine.retrieve.assert_not_called()


def test_answer_uses_assistant_fallback_when_no_chunks(rag_service, app_config) -> None:
    rag_service.config = replace(
        app_config,
        generation=replace(app_config.generation, assistant_fallback=True),
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[])

    def _fake_stream(prompt: str, cancel_event=None):
        assert "Role description" in prompt
        yield "我是 EE-Wiki 助手。"

    rag_service.llm.generate_stream = _fake_stream

    result = rag_service.answer("你可以做什么")
    assert "EE-Wiki" in result.answer
    assert result.citations == []
    rag_service.engine.retrieve.assert_called_once()


def test_stream_answer_uses_assistant_fallback_when_rerank_weak(
    rag_service, app_config
) -> None:
    """Chunks below the weak threshold are treated as no evidence."""
    rag_service.config = replace(
        app_config,
        generation=replace(app_config.generation, assistant_fallback=True),
    )
    chunk = HybridChunk(
        chunk_id="note__misc",
        content="Unrelated content.",
        metadata={"project": "global", "build": "global", "document_type": "engineering_note"},
        citation={"source_file": "data/raw/global/note/note.md", "chunk_id": "note__misc"},
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(
        chunks=[chunk],
        top_rerank_score=-5.0,
    )

    def _fake_stream(prompt: str, cancel_event=None):
        assert "Role description" in prompt
        yield "知识库中没有相关内容。"

    rag_service.llm.generate_stream = _fake_stream

    result = rag_service.stream_answer("你是谁？")
    text = "".join(result.text_chunks)
    assert "知识库" in text
    assert result.citations == []


def test_strong_retrieval_prevents_assistant_fallback(rag_service, app_config) -> None:
    """KB evidence must win regardless of how the question is phrased."""
    rag_service.config = replace(
        app_config,
        generation=replace(app_config.generation, assistant_fallback=True),
    )
    chunk = HybridChunk(
        chunk_id="ipadmanal__astris",
        content="Astris 是设备调试工具，支持 DFU 控制与固件刷写。",
        metadata={"project": "global", "build": "global", "document_type": "engineering_note"},
        citation={
            "source_file": "data/raw/global/note/ipadmanal.md",
            "chunk_id": "ipadmanal__astris",
        },
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(
        chunks=[chunk],
        top_rerank_score=-0.3,
    )

    def _fake_stream(prompt: str, cancel_event=None):
        assert "Role description" not in prompt
        yield "Astris 是调试工具 [1]。"

    rag_service.llm.generate_stream = _fake_stream

    result = rag_service.stream_answer("Astris 可以做什么？")
    text = "".join(result.text_chunks)
    assert "Astris" in text
    assert len(result.citations) == 1


def test_answer_includes_history_in_generation_prompt(rag_service, app_config) -> None:
    """Follow-up turns must be visible to the LLM, not only to query rewrite."""
    rag_service.config = replace(
        app_config,
        generation=replace(app_config.generation, assistant_fallback=False, query_rewrite=False),
    )
    chunk = HybridChunk(
        chunk_id="ipadmanal__discharge",
        content="OSDBatteryTester StateOfCharge --UpperLimit 95",
        metadata={"project": "global", "build": "global", "document_type": "engineering_note"},
        citation={
            "source_file": "data/raw/global/note/ipadmanal.md",
            "chunk_id": "ipadmanal__discharge",
        },
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[chunk], top_rerank_score=1.0)

    captured: dict[str, str] = {}

    def _fake_stream(prompt: str, cancel_event=None):
        captured["prompt"] = prompt
        yield "Plan A: OSDBatteryTester ... [1]"

    rag_service.llm.generate_stream = _fake_stream

    history = [
        ConversationTurn(role="user", content="ipad快速放电指令"),
        ConversationTurn(role="assistant", content="方案 A：OSDBatteryTester StateOfCharge [1]"),
    ]
    rag_service.answer("用英文", history=history)
    assert "Conversation history" in captured["prompt"]
    assert "方案 A：OSDBatteryTester StateOfCharge [1]" in captured["prompt"]
    assert "用英文" in captured["prompt"]


def test_assistant_fallback_includes_history_in_prompt(rag_service, app_config) -> None:
    """Weak retrieval on a follow-up must still expose the previous answer."""
    rag_service.config = replace(
        app_config,
        generation=replace(app_config.generation, assistant_fallback=True, query_rewrite=False),
    )
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[])

    captured: dict[str, str] = {}

    def _fake_stream(prompt: str, cancel_event=None):
        captured["prompt"] = prompt
        yield "Plan A (translated): ..."

    rag_service.llm.generate_stream = _fake_stream

    history = [
        ConversationTurn(role="user", content="ipad快速放电指令"),
        ConversationTurn(role="assistant", content="方案 A：OSDBatteryTester StateOfCharge [1]"),
    ]
    result = rag_service.stream_answer("用英文", history=history)
    "".join(result.text_chunks)
    assert "Conversation history" in captured["prompt"]
    assert "方案 A：OSDBatteryTester StateOfCharge [1]" in captured["prompt"]


def test_assistant_fallback_disabled_returns_insufficient(rag_service) -> None:
    """With the fallback off, empty retrieval returns the static message."""
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[])
    result = rag_service.answer("你是谁？")
    assert result.insufficient_context is True
    assert result.answer == INSUFFICIENT_ANSWER
