"""Tests for explicit RAG query endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_rag_service
from ee_wiki.common.types import Citation, RagAnswer


def test_query_returns_answer_with_citations() -> None:
    mock_answer = RagAnswer(
        answer="VBAT connects to PMIC.",
        citations=[
            Citation(
                source_file="data/raw/logan/p1/note/manual.md",
                chunk_id="manual__power",
                page=0,
                excerpt="VBAT",
            )
        ],
        insufficient_context=False,
    )
    service = MagicMock()
    service.answer.return_value = mock_answer

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)
    response = client.post(
        "/v1/query",
        json={"query": "What is VBAT?", "project": "logan", "build": "p1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "VBAT connects to PMIC."
    assert payload["insufficient_context"] is False
    assert payload["citations"][0]["chunk_id"] == "manual__power"
    service.answer.assert_called_once_with(
        "What is VBAT?",
        target_project="logan",
        target_build="p1",
        document_type=None,
        top_k_final=None,
        task=None,
    )
