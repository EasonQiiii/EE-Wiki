"""Tests for OpenAI-compatible chat endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_rag_service
from ee_wiki.common.types import RagAnswer


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
    assert "created" in payload
    service.answer.assert_called_once_with(
        "What is RMII?",
        target_project="logan",
        target_build="p1",
        document_type=None,
        top_k_final=None,
    )
