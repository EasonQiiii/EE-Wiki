"""Tests for component search API."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_rag_service
from ee_wiki.knowledge.indexer.component_index import ComponentHit


def test_components_search_returns_hits() -> None:
    service = MagicMock()
    service.engine.search_components.return_value = [
        ComponentHit(
            key="U101",
            kind="designator",
            chunk_id="board__p001",
            project="logan",
            build="p1",
            document_type="schematic",
            source_file="data/raw/logan/p1/sch/board.pdf",
            page=1,
            title="board",
            excerpt="U101 PHY",
        )
    ]

    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    client = TestClient(app)

    response = client.get(
        "/v1/components/search",
        params={"q": "U101", "project": "logan", "build": "p1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "U101"
    assert len(payload["hits"]) == 1
    assert payload["hits"][0]["chunk_id"] == "board__p001"
    assert payload["hits"][0]["kind"] == "designator"
