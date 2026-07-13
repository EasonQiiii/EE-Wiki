"""Lightweight structural checks for knowledge graph protocols (V3 P0)."""

from __future__ import annotations

import inspect

from ee_wiki.protocols.graph import GraphQueryBackend, GraphStoreBackend


def test_graph_store_backend_protocol_methods() -> None:
    """GraphStoreBackend exposes save/load/open with documented signatures."""
    required = ("save_graph", "load_graph", "open_graph")
    for name in required:
        assert hasattr(GraphStoreBackend, name), f"missing {name}"
        member = getattr(GraphStoreBackend, name)
        assert callable(member) or inspect.isfunction(member) or inspect.ismethod(member)


def test_graph_query_backend_protocol_methods() -> None:
    """GraphQueryBackend exposes neighbor/path/filter_by_scope."""
    required = ("neighbors", "path", "filter_by_scope")
    for name in required:
        assert hasattr(GraphQueryBackend, name), f"missing {name}"
        member = getattr(GraphQueryBackend, name)
        assert callable(member) or inspect.isfunction(member) or inspect.ismethod(member)


def test_graph_store_backend_is_runtime_checkable_shape() -> None:
    """A minimal stub satisfies GraphStoreBackend structural typing."""

    class _StubStore:
        def save_graph(self, graph_dir, *, graph):  # noqa: ANN001
            return {"path": str(graph_dir)}

        def load_graph(self, graph_dir):  # noqa: ANN001
            return {"path": str(graph_dir)}

        def open_graph(self, graph_dir):  # noqa: ANN001
            return self.load_graph(graph_dir)

    stub: GraphStoreBackend = _StubStore()
    assert stub.open_graph.__name__ == "open_graph"


def test_graph_query_backend_is_runtime_checkable_shape() -> None:
    """A minimal stub satisfies GraphQueryBackend structural typing."""

    class _StubQuery:
        def neighbors(self, node_id, *, project=None, build=None, edge_types=None, max_hops=1):  # noqa: ANN001
            return []

        def path(  # noqa: ANN001
            self,
            source_id,
            target_id,
            *,
            project=None,
            build=None,
            edge_types=None,
            max_depth=8,
        ):
            return None

        def filter_by_scope(self, *, project=None, build=None, node_types=None):  # noqa: ANN001
            return []

    stub: GraphQueryBackend = _StubQuery()
    assert stub.neighbors("n1") == []
    assert stub.path("a", "b") is None
    assert stub.filter_by_scope(project="demo", build="p1") == []
