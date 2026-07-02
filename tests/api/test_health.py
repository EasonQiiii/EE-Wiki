"""Tests for health endpoint queue visibility."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.concurrency import RequestQueueGate
from ee_wiki.api.deps import get_queue_gate


def test_health_returns_queue_stats() -> None:
    gate = RequestQueueGate(max_concurrent=1, max_queue_depth=4, retry_after_seconds=10)
    app = create_app()
    app.dependency_overrides[get_queue_gate] = lambda: gate
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["queue"] == {
        "active": 0,
        "waiting": 0,
        "max_concurrent": 1,
        "max_queue_depth": 4,
        "capacity": 5,
        "capacity_remaining": 5,
    }
