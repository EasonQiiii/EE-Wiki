"""Abstract interfaces for knowledge graph store and query (V3).

See docs/adr/0006-knowledge-graph-store.md for store choice and module boundaries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class GraphStoreBackend(Protocol):
    """Persist and load an offline on-disk knowledge graph bundle under ``data/graph/``."""

    def save_graph(self, graph_dir: Path, *, graph: Any) -> Any:
        """Write a graph bundle to ``graph_dir``.

        Args:
            graph_dir: Target directory (created when missing), typically ``data/graph/``.
            graph: In-memory graph representation (implementation-specific).

        Returns:
            Written manifest metadata (implementation-specific).
        """
        ...

    def load_graph(self, graph_dir: Path) -> Any:
        """Load a persisted graph bundle from ``graph_dir``.

        Args:
            graph_dir: Directory containing manifest, nodes, and edges files.

        Returns:
            Loaded graph ready for query (implementation-specific).
        """
        ...

    def open_graph(self, graph_dir: Path) -> Any:
        """Open a graph store at ``graph_dir`` for read (and optional write) access.

        Args:
            graph_dir: Directory for the on-disk graph bundle.

        Returns:
            Open store handle or loaded graph (implementation-specific).
        """
        ...


class GraphQueryBackend(Protocol):
    """Scope-aware neighbor and path queries over a loaded knowledge graph.

    Implementations must honor product/project/build/common/global scope
    inheritance consistent with retrieval (see ADR 0006, ADR 0011, and
    ``retrieval.scope_inheritance``).
    """

    def neighbors(
        self,
        node_id: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        edge_types: list[str] | None = None,
        max_hops: int = 1,
    ) -> list[dict[str, Any]]:
        """Return neighboring nodes within ``max_hops`` of ``node_id``.

        Args:
            node_id: Starting node identifier.
            product: Optional product scope filter.
            project: Optional project scope filter.
            build: Optional build scope filter (expands to common/global when
                scope inheritance is enabled).
            edge_types: Optional edge-type allowlist; ``None`` means all types.
            max_hops: Maximum traversal depth (default 1 = immediate neighbors).

        Returns:
            Neighbor records with at least ``id``, ``type``, and scope fields
            (``product``, ``project``, ``build``, and preferably ``scope``:
            ``build`` | ``common`` | ``product_common`` | ``global``).
        """
        ...

    def path(
        self,
        source_id: str,
        target_id: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        edge_types: list[str] | None = None,
        max_depth: int = 8,
    ) -> list[dict[str, Any]] | None:
        """Return one path from ``source_id`` to ``target_id`` if found.

        Args:
            source_id: Start node identifier.
            target_id: End node identifier.
            product: Optional product scope filter.
            project: Optional project scope filter.
            build: Optional build scope filter (with scope inheritance).
            edge_types: Optional edge-type allowlist.
            max_depth: Maximum path length in edges.

        Returns:
            Ordered list of path steps (nodes and/or edges as dicts), or
            ``None`` when no path exists within ``max_depth`` and scope.
        """
        ...

    def filter_by_scope(
        self,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
        node_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return nodes matching product/project/build scope (with inheritance).

        Args:
            product: Optional product filter; ``None`` may mean all products
                (implementation-defined).
            project: Optional project filter.
            build: Optional build filter; when set with inheritance, include
                shared ``common`` tiers and ``global``.
            node_types: Optional node-type allowlist.

        Returns:
            Matching node records with explicit scope labels.
        """
        ...
