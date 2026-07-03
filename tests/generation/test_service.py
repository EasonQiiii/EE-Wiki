"""Tests for RAG service orchestration."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from ee_wiki.generation.service import INSUFFICIENT_ANSWER, RagService
from ee_wiki.retrieval.hybrid.engine import HybridChunk, RetrievalResult


@pytest.fixture
def rag_service(app_config):
    config = replace(
        app_config,
        generation=replace(app_config.generation, intent_routing=False),
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


def test_answer_assistant_meta_skips_retrieval(rag_service, app_config, repo_root) -> None:
    from dataclasses import replace
    from unittest.mock import patch

    rag_service.config = replace(
        app_config,
        generation=replace(app_config.generation, intent_routing=True),
    )

    def _fake_stream(prompt: str, cancel_event=None):
        assert "Role description" in prompt
        yield "我是 EE-Wiki 助手。"

    rag_service.llm.generate_stream = _fake_stream

    with patch(
        "ee_wiki.generation.service.classify_query_route",
        return_value=__import__(
            "ee_wiki.generation.intent_router", fromlist=["QueryRoute"]
        ).QueryRoute.ASSISTANT_META,
    ):
        result = rag_service.answer("你可以做什么")
    assert "EE-Wiki" in result.answer
    assert result.citations == []
    rag_service.engine.retrieve.assert_not_called()


def test_stream_answer_assistant_meta_skips_retrieval(rag_service, app_config) -> None:
    from dataclasses import replace
    from unittest.mock import patch

    rag_service.config = replace(
        app_config,
        generation=replace(app_config.generation, intent_routing=True),
    )

    def _fake_stream(prompt: str, cancel_event=None):
        yield "我是 EE-Wiki 助手。"

    rag_service.llm.generate_stream = _fake_stream

    with patch(
        "ee_wiki.generation.service.classify_query_route",
        return_value=__import__(
            "ee_wiki.generation.intent_router", fromlist=["QueryRoute"]
        ).QueryRoute.ASSISTANT_META,
    ):
        result = rag_service.stream_answer("你是谁？")
    text = "".join(result.text_chunks)
    assert "EE-Wiki" in text
    assert result.citations == []
    rag_service.engine.retrieve.assert_not_called()
