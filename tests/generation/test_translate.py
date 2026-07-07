"""Tests for translation task handling."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import pytest

from ee_wiki.generation.prepare import PREPARE_MAX_TOKENS
from ee_wiki.generation.service import RagService
from ee_wiki.generation.translate import (
    TRANSLATE_TASK,
    build_translation_prompt,
    is_translation_task,
)
from ee_wiki.retrieval.hybrid.engine import RetrievalResult
from ee_wiki.retrieval.rewrite import ConversationTurn


@pytest.fixture
def rag_service(app_config):
    config = replace(
        app_config,
        generation=replace(
            app_config.generation,
            assistant_fallback=False,
            task_classification=True,
            query_prepare="merged",
        ),
    )
    engine = MagicMock()
    llm = MagicMock()
    llm.generate_stream = None
    llm.generate.return_value = "QUERY: ipad fast discharge\nTASK: translate"
    return RagService(config=config, engine=engine, llm=llm)


def test_is_translation_task() -> None:
    assert is_translation_task(TRANSLATE_TASK)
    assert not is_translation_task("wiki")
    assert not is_translation_task(None)


def test_build_translation_prompt_includes_history(repo_root) -> None:
    history = [
        ConversationTurn(role="user", content="ipad快速放电指令"),
        ConversationTurn(role="assistant", content="方案 A：OSDBatteryTester [1]"),
    ]
    prompt = build_translation_prompt(
        repo_root,
        question="in English",
        history=history,
    )
    assert "中英互译" in prompt
    assert "方案 A：OSDBatteryTester [1]" in prompt
    assert "in English" in prompt


def test_answer_translation_when_prepare_classifies_translate(rag_service) -> None:
    rag_service.engine.retrieve = MagicMock()
    captured: dict[str, str] = {}

    def _fake_stream(prompt: str, cancel_event=None, max_new_tokens=None):
        if max_new_tokens and max_new_tokens <= PREPARE_MAX_TOKENS:
            yield "QUERY: ipad fast discharge\nTASK: translate"
            return
        captured["prompt"] = prompt
        yield "Plan A: OSDBatteryTester ... [1]"

    rag_service.llm.generate_stream = _fake_stream

    history = [
        ConversationTurn(role="user", content="ipad快速放电指令"),
        ConversationTurn(role="assistant", content="方案 A：OSDBatteryTester StateOfCharge [1]"),
    ]
    result = rag_service.answer("in English", history=history)

    rag_service.engine.retrieve.assert_not_called()
    assert "Plan A" in result.answer
    assert "中英互译" in captured["prompt"]
    assert result.citations == []


def test_stream_answer_translation_when_caller_sets_task(rag_service) -> None:
    rag_service.engine.retrieve = MagicMock()

    def _fake_stream(prompt: str, cancel_event=None):
        yield "Translated body."

    rag_service.llm.generate_stream = _fake_stream

    result = rag_service.stream_answer("please render in Chinese", task=TRANSLATE_TASK)
    text = "".join(result.text_chunks)

    rag_service.engine.retrieve.assert_not_called()
    assert "Translated body." in text
    assert result.citations == []


def test_non_translation_still_retrieves(rag_service) -> None:
    rag_service.llm.generate.return_value = "QUERY: RMII interface\nTASK: wiki"
    rag_service.engine.retrieve.return_value = RetrievalResult(chunks=[], top_rerank_score=None)

    rag_service.answer("RMII 接口说明")

    rag_service.engine.retrieve.assert_called_once()
