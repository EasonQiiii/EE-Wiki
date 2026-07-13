"""Tests for project inventory HTTP route."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_rag_service
from ee_wiki.retrieval.index_inventory import IndexInventory, ProjectInventoryEntry


class _FakeEngine:
    def get_index_inventory(self) -> IndexInventory:
        return IndexInventory(
            chunk_count=3,
            projects=(
                ProjectInventoryEntry(
                    project="global",
                    builds=("global",),
                    chunk_count=1,
                    is_enterprise=True,
                ),
                ProjectInventoryEntry(
                    project="logan",
                    builds=("p1",),
                    chunk_count=2,
                    is_enterprise=False,
                ),
            ),
            product_count=1,
            enterprise_project="global",
            project_shared_build="common",
        )


class _FakeService:
    engine = _FakeEngine()


def test_list_projects_endpoint() -> None:
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: _FakeService()
    client = TestClient(app)
    response = client.get("/v1/projects")
    assert response.status_code == 200
    payload = response.json()
    assert payload["chunk_count"] == 3
    assert payload["product_count"] == 1
    assert len(payload["projects"]) == 2
    assert payload["projects"][1]["project"] == "logan"
