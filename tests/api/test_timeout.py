"""Tests for request timeout handling."""

from __future__ import annotations

import time
from dataclasses import replace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_config, get_rag_service
from ee_wiki.common.types import RagAnswer
from ee_wiki.generation.llm.errors import LlmTimeoutError


def test_chat_completions_returns_504_on_llm_timeout(app_config) -> None:
    service = MagicMock()
    service.stream_answer.side_effect = LlmTimeoutError("LLM generation exceeded 120s")

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "ee-wiki", "messages": [{"role": "user", "content": "slow"}]},
    )

    assert response.status_code == 504
    assert response.json()["detail"]["message"] == "请求超时，请重试"


def test_query_returns_504_on_request_timeout(app_config) -> None:
    service = MagicMock()

    def slow_answer(*_args, **_kwargs):
        time.sleep(0.2)
        return RagAnswer(answer="late", citations=[], insufficient_context=False)

    service.answer.side_effect = slow_answer
    config = replace(app_config, api=replace(app_config.api, request_timeout_seconds=0.05))

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: config
    client = TestClient(app)

    response = client.post("/v1/query", json={"query": "slow question"})
    assert response.status_code == 504
    assert response.json()["detail"]["error"] == "request_timeout"
