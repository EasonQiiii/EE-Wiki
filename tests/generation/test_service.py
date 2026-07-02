"""Tests for RAG service orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ee_wiki.generation.service import INSUFFICIENT_ANSWER, RagService
from ee_wiki.retrieval.hybrid.engine import HybridChunk


@pytest.fixture
def rag_service(app_config):
    engine = MagicMock()
    llm = MagicMock()
    return RagService(config=app_config, engine=engine, llm=llm)


def test_answer_returns_insufficient_when_no_chunks(rag_service) -> None:
    rag_service.engine.retrieve.return_value = []
    result = rag_service.answer("unknown topic", target_project="logan", target_build="p1")
    assert result.insufficient_context is True
    assert result.answer == INSUFFICIENT_ANSWER
    assert result.citations == []
    rag_service.llm.generate.assert_not_called()


def test_answer_generates_from_retrieved_chunks(rag_service, repo_root) -> None:
    chunk = HybridChunk(
        chunk_id="note__power",
        content="VBAT connects to PMIC.",
        metadata={"project": "logan", "build": "p1", "document_type": "engineering_note"},
        citation={
            "source_file": "data/raw/logan/p1/note/note.md",
            "chunk_id": "note__power",
            "page": 0,
            "excerpt": "VBAT",
        },
    )
    rag_service.engine.retrieve.return_value = [chunk]
    rag_service.llm.generate.return_value = "VBAT is connected to the PMIC [1]."

    result = rag_service.answer("What is VBAT?", target_project="logan", target_build="p1")
    assert result.insufficient_context is False
    assert "VBAT" in result.answer
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == "note__power"
    rag_service.llm.generate.assert_called_once()
    prompt = rag_service.llm.generate.call_args.args[0]
    assert "VBAT connects to PMIC." in prompt
    assert "What is VBAT?" in prompt
