"""In-memory knowledge graph types for the V3 JSONL bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ee_wiki.common.types import DataLayoutConfig

NodeType = Literal[
    "Component",
    "Net",
    "Document",
    "Product",
    "Project",
    "Build",
    "Case",
    "Rail",
]
EdgeType = Literal[
    "connects_to",
    "appears_in",
    "same_as",
    "supplies",
    "derived_from",
    "mentions",
    "caused_by",
    "related_to",
]
ScopeLabel = Literal["build", "common", "product_common", "global"]

NODE_COMPONENT: NodeType = "Component"
NODE_NET: NodeType = "Net"
NODE_DOCUMENT: NodeType = "Document"
NODE_PRODUCT: NodeType = "Product"
NODE_PROJECT: NodeType = "Project"
NODE_BUILD: NodeType = "Build"
NODE_CASE: NodeType = "Case"
NODE_RAIL: NodeType = "Rail"

EDGE_CONNECTS_TO: EdgeType = "connects_to"
EDGE_APPEARS_IN: EdgeType = "appears_in"
EDGE_SAME_AS: EdgeType = "same_as"
EDGE_SUPPLIES: EdgeType = "supplies"
EDGE_DERIVED_FROM: EdgeType = "derived_from"
EDGE_MENTIONS: EdgeType = "mentions"
EDGE_CAUSED_BY: EdgeType = "caused_by"
EDGE_RELATED_TO: EdgeType = "related_to"

GRAPH_SCHEMA_VERSION = 4


def scope_label(
    product: str,
    project: str,
    build: str,
    layout: DataLayoutConfig,
) -> ScopeLabel:
    """Return the knowledge-layer label for a ``(product, project, build)`` triple.

    Args:
        product: Metadata product segment.
        project: Metadata project segment.
        build: Metadata build segment.
        layout: Path naming configuration.

    Returns:
        ``global``, ``product_common``, ``common`` (project common), or ``build``.
    """
    if product == layout.global_segment:
        return "global"
    if project == layout.common_segment:
        return "product_common"
    if build == layout.common_segment:
        return "common"
    return "build"


@dataclass(frozen=True)
class GraphNode:
    """One knowledge-graph node persisted in ``nodes.jsonl``."""

    id: str
    type: str
    product: str
    project: str
    build: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this node for JSONL persistence."""
        payload: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "product": self.product,
            "project": self.project,
            "build": self.build,
        }
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphNode:
        """Deserialize a node from a JSON object."""
        attrs = data.get("attributes", {})
        return cls(
            id=str(data.get("id", "")),
            type=str(data.get("type", "")),
            product=str(data.get("product", "")),
            project=str(data.get("project", "")),
            build=str(data.get("build", "")),
            attributes=dict(attrs) if isinstance(attrs, dict) else {},
        )

    def with_scope(self, layout: DataLayoutConfig) -> dict[str, Any]:
        """Return a query-facing dict including an explicit ``scope`` label."""
        payload = self.to_dict()
        payload["scope"] = scope_label(self.product, self.project, self.build, layout)
        return payload


@dataclass(frozen=True)
class GraphEdge:
    """One knowledge-graph edge persisted in ``edges.jsonl``."""

    source: str
    target: str
    type: str
    product: str = ""
    project: str = ""
    build: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this edge for JSONL persistence."""
        payload: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "type": self.type,
        }
        if self.product:
            payload["product"] = self.product
        if self.project:
            payload["project"] = self.project
        if self.build:
            payload["build"] = self.build
        if self.attributes:
            payload["attributes"] = dict(self.attributes)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphEdge:
        """Deserialize an edge from a JSON object."""
        attrs = data.get("attributes", {})
        return cls(
            source=str(data.get("source", "")),
            target=str(data.get("target", "")),
            type=str(data.get("type", "")),
            product=str(data.get("product", "")),
            project=str(data.get("project", "")),
            build=str(data.get("build", "")),
            attributes=dict(attrs) if isinstance(attrs, dict) else {},
        )

    def with_scope(self, layout: DataLayoutConfig) -> dict[str, Any]:
        """Return a query-facing dict including an explicit ``scope`` label."""
        payload = self.to_dict()
        if self.product or self.project or self.build:
            payload["scope"] = scope_label(
                self.product, self.project, self.build, layout
            )
        return payload


@dataclass
class KnowledgeGraph:
    """In-memory graph with undirected adjacency for neighbor/path queries."""

    nodes: dict[str, GraphNode] = field(default_factory=dict)
    edges: list[GraphEdge] = field(default_factory=list)
    adjacency: dict[str, list[tuple[str, GraphEdge]]] = field(default_factory=dict)
    source_fingerprints: dict[str, Any] = field(default_factory=dict)

    def add_node(self, node: GraphNode) -> GraphNode:
        """Insert or replace a node by id and return the stored node.

        Args:
            node: Node to upsert.

        Returns:
            The node stored under ``node.id`` (existing wins if already present
            so first write keeps attributes).
        """
        existing = self.nodes.get(node.id)
        if existing is not None:
            return existing
        self.nodes[node.id] = node
        self.adjacency.setdefault(node.id, [])
        return node

    def add_edge(self, edge: GraphEdge) -> None:
        """Append an edge and register both adjacency directions.

        Args:
            edge: Edge whose endpoints must already exist (or will be skipped
                when either endpoint is missing).
        """
        if edge.source not in self.nodes or edge.target not in self.nodes:
            return
        self.edges.append(edge)
        self.adjacency.setdefault(edge.source, []).append((edge.target, edge))
        self.adjacency.setdefault(edge.target, []).append((edge.source, edge))

    def rebuild_adjacency(self) -> None:
        """Rebuild undirected adjacency from ``edges`` (used after load)."""
        self.adjacency = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                continue
            self.adjacency.setdefault(edge.source, []).append((edge.target, edge))
            self.adjacency.setdefault(edge.target, []).append((edge.source, edge))
