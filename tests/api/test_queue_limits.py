"""Tests for RAG endpoint queue limits."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.concurrency import RequestQueueGate
from ee_wiki.api.deps import get_queue_gate, get_rag_service
from ee_wiki.common.types import RagAnswer


def test_query_returns_503_when_queue_is_full() -> None:
    gate = RequestQueueGate(max_concurrent=1, max_queue_depth=0, retry_after_seconds=20)
    release = threading.Event()
    entered = threading.Event()

    from unittest.mock import MagicMock

    mock_service = MagicMock()

    def slow_answer(*_args, **_kwargs) -> RagAnswer:
        entered.set()
        release.wait(timeout=5)
        return RagAnswer(answer="done", citations=[], insufficient_context=False)

    mock_service.answer.side_effect = slow_answer

    app = create_app()
    app.dependency_overrides[get_queue_gate] = lambda: gate
    app.dependency_overrides[get_rag_service] = lambda: mock_service
    client = TestClient(app)

    blocker = threading.Thread(
        target=lambda: client.post("/v1/query", json={"query": "first"}),
    )
    blocker.start()
    assert entered.wait(timeout=5)

    response = client.post("/v1/query", json={"query": "second"})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "20"
    assert response.headers["X-EE-Wiki-Queue-Active"] == "1"
    assert response.headers["X-EE-Wiki-Queue-Waiting"] == "0"
    assert response.headers["X-EE-Wiki-Queue-Capacity-Remaining"] == "0"
    payload = response.json()["detail"]
    assert payload["error"] == "queue_full"
    assert payload["retry_after_seconds"] == 20

    release.set()
    blocker.join(timeout=5)
