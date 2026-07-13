"""Knowledge graph package (V3) — store, build, and query (ADR 0006).

Build from indexed chunks + ``components.json`` + ``cases.json`` into an offline
JSONL bundle under ``data/graph/``. Query neighbors, paths, scope filters, and
power-tree (V3 P3) via :class:`GraphQuery` / :class:`PowerTreeQuery`.
"""

from __future__ import annotations

from ee_wiki.graph.build import (
    GraphBuildError,
    GraphBuildResult,
    build_and_save_graph,
    build_graph_from_chunks,
)
from ee_wiki.graph.models import (
    EDGE_APPEARS_IN,
    EDGE_CAUSED_BY,
    EDGE_CONNECTS_TO,
    EDGE_DERIVED_FROM,
    EDGE_MENTIONS,
    EDGE_RELATED_TO,
    EDGE_SAME_AS,
    EDGE_SUPPLIES,
    NODE_BUILD,
    NODE_CASE,
    NODE_COMPONENT,
    NODE_DOCUMENT,
    NODE_NET,
    NODE_PROJECT,
    NODE_RAIL,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    scope_label,
)
from ee_wiki.graph.power_tree import PowerTreeQuery, open_power_query
from ee_wiki.graph.query import GraphQuery, open_query
from ee_wiki.graph.store import GraphManifest, GraphStoreError, JsonlGraphStore, graph_exists

__all__ = [
    "EDGE_APPEARS_IN",
    "EDGE_CAUSED_BY",
    "EDGE_CONNECTS_TO",
    "EDGE_DERIVED_FROM",
    "EDGE_MENTIONS",
    "EDGE_RELATED_TO",
    "EDGE_SAME_AS",
    "EDGE_SUPPLIES",
    "NODE_BUILD",
    "NODE_CASE",
    "NODE_COMPONENT",
    "NODE_DOCUMENT",
    "NODE_NET",
    "NODE_PROJECT",
    "NODE_RAIL",
    "GraphBuildError",
    "GraphBuildResult",
    "GraphEdge",
    "GraphManifest",
    "GraphNode",
    "GraphQuery",
    "GraphStoreError",
    "JsonlGraphStore",
    "KnowledgeGraph",
    "PowerTreeQuery",
    "build_and_save_graph",
    "build_graph_from_chunks",
    "graph_exists",
    "open_power_query",
    "open_query",
    "scope_label",
]
