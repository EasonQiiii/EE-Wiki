"""Tests for OpenAI-compatible chat endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_rag_service
from ee_wiki.common.types import Citation, RagAnswer
from ee_wiki.generation.service import AnswerStreamResult


def test_chat_completions_uses_last_user_message() -> None:
    mock_answer = RagAnswer(
        answer="RMII uses ETH_MDIO.",
        citations=[],
        insufficient_context=False,
    )
    service = MagicMock()
    service.answer.return_value = mock_answer

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "What is RMII?"},
            ],
            "project": "logan",
            "build": "p1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "RMII uses ETH_MDIO."
    assert payload["model"] == "ee-wiki"
    assert payload["sources"] == []
    assert "created" in payload
    service.answer.assert_called_once_with(
        "What is RMII?",
        target_project="logan",
        target_build="p1",
        document_type=None,
        top_k_final=None,
    )


def test_chat_completions_returns_open_webui_sources() -> None:
    citations = [
        Citation(
            source_file="data/raw/logan/p1/note/manual.md",
            chunk_id="manual__power",
            page=0,
            excerpt="VBAT connects to PMIC.",
            url="http://localhost:8080/v1/sources/logan/p1/note/manual.md#power",
        ),
    ]
    mock_answer = RagAnswer(
        answer="VBAT is connected to the PMIC [1].",
        citations=citations,
        insufficient_context=False,
    )
    service = MagicMock()
    service.answer.return_value = mock_answer

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "messages": [{"role": "user", "content": "What is VBAT?"}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["choices"][0]["message"]["content"] == "VBAT is connected to the PMIC [1]."
    assert payload["citations"][0]["url"].endswith("/v1/sources/logan/p1/note/manual.md#power")
    assert payload["sources"][0]["source"]["url"] == citations[0].url
    assert payload["sources"][0]["source"]["name"] == "[1] manual.md"


def test_chat_completions_stream_emits_sources_chunk() -> None:
    citations = [
        Citation(
            source_file="data/raw/logan/p1/note/manual.md",
            chunk_id="manual__power",
            page=0,
            excerpt="VBAT connects to PMIC.",
            url="http://localhost:8080/v1/sources/logan/p1/note/manual.md#power",
        ),
    ]

    def _text_chunks():
        yield "VBAT answer [1]."

    service = MagicMock()
    service.stream_answer.return_value = AnswerStreamResult(
        citations=citations,
        text_chunks=_text_chunks(),
    )

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "ee-wiki",
            "stream": True,
            "messages": [{"role": "user", "content": "What is VBAT?"}],
        },
    )

    assert response.status_code == 200
    body = response.text
    assert '"sources"' in body
    assert '"event"' in body
    assert "VBAT answer [1]." in body
    assert "<a href=" not in body
