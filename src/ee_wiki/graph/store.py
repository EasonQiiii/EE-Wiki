"""Offline JSONL knowledge-graph store under ``data/graph/`` (ADR 0006)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.graph.models import GRAPH_SCHEMA_VERSION, GraphEdge, GraphNode, KnowledgeGraph

logger = get_logger(__name__)

MANIFEST_NAME = "manifest.json"
NODES_NAME = "nodes.jsonl"
EDGES_NAME = "edges.jsonl"


class GraphStoreError(EEWikiError):
    """Failed to read or write a persisted knowledge-graph bundle."""


@dataclass(frozen=True)
class GraphManifest:
    """Metadata describing a built on-disk graph bundle."""

    schema_version: int
    built_at: str
    node_count: int
    edge_count: int
    source_fingerprints: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Serialize manifest for ``manifest.json``."""
        return {
            "schema_version": self.schema_version,
            "built_at": self.built_at,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "source_fingerprints": self.source_fingerprints,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphManifest:
        """Deserialize manifest from JSON."""
        return cls(
            schema_version=int(data.get("schema_version", data.get("version", 0))),
            built_at=str(data.get("built_at", "")),
            node_count=int(data.get("node_count", 0)),
            edge_count=int(data.get("edge_count", 0)),
            source_fingerprints=dict(data.get("source_fingerprints", {})),
        )


def graph_paths(graph_dir: Path) -> dict[str, Path]:
    """Return canonical file paths under ``data/graph/``.

    Args:
        graph_dir: Graph bundle directory.

    Returns:
        Mapping of logical names to absolute paths.
    """
    root = graph_dir.resolve()
    return {
        "manifest": root / MANIFEST_NAME,
        "nodes": root / NODES_NAME,
        "edges": root / EDGES_NAME,
    }


def graph_exists(graph_dir: Path) -> bool:
    """Return whether a complete graph bundle exists under ``graph_dir``."""
    paths = graph_paths(graph_dir)
    return all(path.is_file() for path in paths.values())


class JsonlGraphStore:
    """Persist and load the ADR 0006 JSONL graph bundle."""

    def save_graph(self, graph_dir: Path, *, graph: KnowledgeGraph) -> GraphManifest:
        """Write a graph bundle to ``graph_dir``.

        Args:
            graph_dir: Target directory (created when missing).
            graph: In-memory knowledge graph.

        Returns:
            Written manifest metadata.

        Raises:
            GraphStoreError: If writing fails.
        """
        graph_dir.mkdir(parents=True, exist_ok=True)
        paths = graph_paths(graph_dir)
        manifest = GraphManifest(
            schema_version=GRAPH_SCHEMA_VERSION,
            built_at=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            node_count=len(graph.nodes),
            edge_count=len(graph.edges),
            source_fingerprints=dict(graph.source_fingerprints),
        )
        try:
            paths["manifest"].write_text(
                json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with paths["nodes"].open("w", encoding="utf-8") as handle:
                for node_id in sorted(graph.nodes):
                    handle.write(
                        json.dumps(graph.nodes[node_id].to_dict(), ensure_ascii=False) + "\n"
                    )
            with paths["edges"].open("w", encoding="utf-8") as handle:
                for edge in graph.edges:
                    handle.write(json.dumps(edge.to_dict(), ensure_ascii=False) + "\n")
        except OSError as exc:
            raise GraphStoreError(f"Failed to write graph under {graph_dir}") from exc

        logger.info(
            "Wrote graph with %d node(s) and %d edge(s) to %s",
            manifest.node_count,
            manifest.edge_count,
            graph_dir,
        )
        return manifest

    def load_graph(self, graph_dir: Path) -> KnowledgeGraph:
        """Load a persisted graph bundle from ``graph_dir``.

        Args:
            graph_dir: Directory containing manifest, nodes, and edges files.

        Returns:
            Loaded graph with rebuilt adjacency.

        Raises:
            GraphStoreError: If required files are missing or corrupt.
        """
        paths = graph_paths(graph_dir)
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            raise GraphStoreError(
                f"Graph incomplete under {graph_dir}, missing: {', '.join(missing)}"
            )

        try:
            manifest = GraphManifest.from_dict(
                json.loads(paths["manifest"].read_text(encoding="utf-8"))
            )
            nodes: dict[str, GraphNode] = {}
            with paths["nodes"].open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    node = GraphNode.from_dict(json.loads(line))
                    if node.id:
                        nodes[node.id] = node
            edges: list[GraphEdge] = []
            with paths["edges"].open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    edges.append(GraphEdge.from_dict(json.loads(line)))
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise GraphStoreError(f"Failed to load graph from {graph_dir}") from exc

        graph = KnowledgeGraph(
            nodes=nodes,
            edges=edges,
            source_fingerprints=dict(manifest.source_fingerprints),
        )
        graph.rebuild_adjacency()
        if manifest.node_count and manifest.node_count != len(nodes):
            logger.warning(
                "Manifest node_count=%d but loaded %d node(s)",
                manifest.node_count,
                len(nodes),
            )
        logger.info(
            "Loaded graph with %d node(s) and %d edge(s) from %s",
            len(nodes),
            len(edges),
            graph_dir,
        )
        return graph

    def open_graph(self, graph_dir: Path) -> KnowledgeGraph:
        """Open a graph store at ``graph_dir`` for read access.

        Args:
            graph_dir: Directory for the on-disk graph bundle.

        Returns:
            Loaded in-memory graph.
        """
        return self.load_graph(graph_dir)
