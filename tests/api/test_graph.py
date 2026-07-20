"""Tests for knowledge-graph HTTP routes (V3 P5)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_graph_query


def _mock_gq() -> MagicMock:
    gq = MagicMock()
    gq.resolve_node.side_effect = lambda token, product=None, project=None, build=None: (
        f"component:iphone/logan/p1:{token.upper()}" if token.strip() else None
    )
    gq.get_node.return_value = {
        "id": "component:iphone/logan/p1:U101",
        "type": "Component",
        "project": "logan",
        "build": "p1",
        "scope": "build",
    }
    gq.neighbors.return_value = [
        {
            "id": "net:iphone/logan/p1:NET_VCC",
            "type": "Net",
            "project": "logan",
            "build": "p1",
            "scope": "build",
            "hops": 1,
        }
    ]
    gq.path.return_value = [
        {"id": "component:iphone/logan/p1:U101", "type": "Component", "scope": "build"},
        {"type": "connects_to", "scope": "build"},
        {"id": "net:iphone/logan/p1:NET_VCC", "type": "Net", "scope": "build"},
    ]
    gq.filter_by_scope.return_value = [
        {
            "id": "component:iphone/logan/p1:U101",
            "type": "Component",
            "project": "logan",
            "build": "p1",
            "scope": "build",
        }
    ]
    return gq


def test_graph_neighbors_returns_hits() -> None:
    gq = _mock_gq()
    app = create_app()
    app.dependency_overrides[get_graph_query] = lambda: gq
    client = TestClient(app)

    response = client.get(
        "/v1/graph/neighbors",
        params={"q": "U101", "product": "iphone", "project": "logan", "build": "p1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolved_id"] == "component:iphone/logan/p1:U101"
    assert len(payload["neighbors"]) == 1
    assert payload["neighbors"][0]["id"] == "net:iphone/logan/p1:NET_VCC"


def test_graph_path_found() -> None:
    gq = _mock_gq()
    app = create_app()
    app.dependency_overrides[get_graph_query] = lambda: gq
    client = TestClient(app)

    response = client.get(
        "/v1/graph/path",
        params={
            "source": "U101",
            "target": "NET_VCC",
            "product": "iphone",
            "project": "logan",
            "build": "p1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert len(payload["path"]) == 3


def test_graph_nodes_filter() -> None:
    gq = _mock_gq()
    app = create_app()
    app.dependency_overrides[get_graph_query] = lambda: gq
    client = TestClient(app)

    response = client.get(
        "/v1/graph/nodes",
        params={"product": "iphone", "project": "logan", "build": "p1", "node_types": "Component"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["node_types"] == ["Component"]
    gq.filter_by_scope.assert_called_once()


def test_graph_node_open() -> None:
    gq = _mock_gq()
    app = create_app()
    app.dependency_overrides[get_graph_query] = lambda: gq
    client = TestClient(app)

    response = client.get(
        "/v1/graph/node",
        params={"q": "U101", "product": "iphone", "project": "logan", "build": "p1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["node"]["id"] == "component:iphone/logan/p1:U101"


def test_graph_unavailable_returns_503() -> None:
    app = create_app()
    app.dependency_overrides[get_graph_query] = lambda: None
    client = TestClient(app)

    response = client.get("/v1/graph/neighbors", params={"q": "U101"})
    assert response.status_code == 503
