"""Scope-aware neighbor and path queries over a loaded knowledge graph."""

from __future__ import annotations

from collections import deque
from typing import Any

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.graph.ids import (
    case_node_id,
    component_node_id,
    net_node_id,
    part_node_id,
    rail_node_id,
)
from ee_wiki.graph.models import KnowledgeGraph, scope_label
from ee_wiki.ingestion.path_metadata import allowed_scope_triples

_SCOPE_RANK = {"build": 0, "common": 1, "product_common": 2, "global": 3}


def _scope_rank(product: str, project: str, build: str, layout: DataLayoutConfig) -> int:
    """Rank build > project common > product common > global."""
    return _SCOPE_RANK[scope_label(product, project, build, layout)]


class GraphQuery:
    """Query API implementing :class:`~ee_wiki.protocols.graph.GraphQueryBackend`."""

    def __init__(
        self,
        graph: KnowledgeGraph,
        *,
        layout: DataLayoutConfig,
        scope_inheritance: bool = True,
    ) -> None:
        """Bind a loaded graph and scope rules.

        Args:
            graph: In-memory knowledge graph with adjacency.
            layout: Path naming configuration for scope expansion.
            scope_inheritance: When true, expand build filters to common/global.
        """
        self.graph = graph
        self.layout = layout
        self.scope_inheritance = scope_inheritance

    def _allowed_scopes(
        self,
        *,
        product: str | None,
        project: str | None,
        build: str | None,
    ) -> set[tuple[str, str, str]] | None:
        """Return allowed ``(product, project, build)`` triples, or ``None`` for no filter."""
        return allowed_scope_triples(
            self.layout,
            product=product,
            project=project,
            build=build,
            scope_inheritance=self.scope_inheritance,
        )

    def _node_in_scope(
        self,
        node_id: str,
        allowed: set[tuple[str, str, str]] | None,
    ) -> bool:
        if allowed is None:
            return True
        node = self.graph.nodes.get(node_id)
        if node is None:
            return False
        # Part identity nodes live under the enterprise scope; concrete nodes
        # are filtered by the full triple so identical project/build slugs in
        # another product can never leak in.
        return (node.product, node.project, node.build) in allowed

    def _edge_allowed(
        self,
        edge_type: str,
        edge_types: list[str] | None,
    ) -> bool:
        if edge_types is None:
            return True
        return edge_type in edge_types

    def _sort_key(self, node_id: str) -> tuple[int, str]:
        node = self.graph.nodes[node_id]
        return (
            _scope_rank(node.product, node.project, node.build, self.layout),
            node_id,
        )

    def resolve_node(
        self,
        token: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
    ) -> str | None:
        """Resolve a user token to a graph node id within optional scope.

        Accepts a full node id, or a designator / net / rail / case / part
        token. When ``product``, ``project``, and ``build`` are set, scoped id
        forms are tried first.

        Args:
            token: Designator, net/rail/case name, part number, or full node id.
            product: Preferred product for scoped id construction.
            project: Preferred project for scoped id construction.
            build: Preferred build for scoped id construction.

        Returns:
            Node id when found, else ``None``.
        """
        cleaned = token.strip()
        if not cleaned:
            return None
        if cleaned in self.graph.nodes:
            return cleaned

        prod = product or ""
        proj = project or ""
        bld = build or ""
        candidates: list[str] = []
        if prod and proj and bld:
            candidates.extend(
                [
                    rail_node_id(prod, proj, bld, cleaned),
                    net_node_id(prod, proj, bld, cleaned),
                    component_node_id(prod, proj, bld, cleaned),
                    case_node_id(prod, proj, bld, cleaned),
                ]
            )
        candidates.append(part_node_id(cleaned))

        allowed = self._allowed_scopes(product=product, project=project, build=build)
        for candidate in candidates:
            if candidate in self.graph.nodes and self._node_in_scope(candidate, allowed):
                return candidate

        upper = cleaned.upper().removeprefix("NET_")
        matches: list[str] = []
        for node_id, node in self.graph.nodes.items():
            if not self._node_in_scope(node_id, allowed):
                continue
            attrs = node.attributes or {}
            name = str(attrs.get("name") or attrs.get("key") or "").upper()
            if name == upper or name == cleaned.upper():
                matches.append(node_id)
            elif node_id.upper().endswith(f":{upper}") or node_id.upper().endswith(
                f":{cleaned.upper()}"
            ):
                matches.append(node_id)
        if not matches:
            return None
        matches.sort(key=self._sort_key)
        return matches[0]

    def get_node(
        self,
        node_id: str,
        *,
        product: str | None = None,
        project: str | None = None,
        build: str | None = None,
    ) -> dict[str, Any] | None:
        """Return one node record with scope label, or ``None`` if missing/out of scope.

        Args:
            node_id: Exact node identifier (resolve tokens via :meth:`resolve_node`).
            product: Optional product scope filter.
            project: Optional project scope filter.
            build: Optional build scope filter.

        Returns:
            Node dict with ``scope``, or ``None``.
        """
        if node_id not in self.graph.nodes:
            return None
        allowed = self._allowed_scopes(product=product, project=project, build=build)
        if not self._node_in_scope(node_id, allowed):
            return None
        return self.graph.nodes[node_id].with_scope(self.layout)

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
            build: Optional build scope filter (expands when inheritance is on).
            edge_types: Optional edge-type allowlist; ``None`` means all types.
            max_hops: Maximum traversal depth (default 1).

        Returns:
            Neighbor records with ``id``, ``type``, ``product``, ``project``,
            ``build``, ``scope``, and ``hops``. Ordered build > common > global.
        """
        if node_id not in self.graph.nodes or max_hops < 1:
            return []

        allowed = self._allowed_scopes(product=product, project=project, build=build)
        visited: set[str] = {node_id}
        # (node_id, hops)
        frontier: deque[tuple[str, int]] = deque([(node_id, 0)])
        found: dict[str, int] = {}

        while frontier:
            current, hops = frontier.popleft()
            if hops >= max_hops:
                continue
            for neighbor_id, edge in self.graph.adjacency.get(current, []):
                if not self._edge_allowed(edge.type, edge_types):
                    continue
                if neighbor_id in visited:
                    continue
                if not self._node_in_scope(neighbor_id, allowed):
                    continue
                visited.add(neighbor_id)
                next_hops = hops + 1
                found[neighbor_id] = next_hops
                if next_hops < max_hops:
                    frontier.append((neighbor_id, next_hops))

        results: list[dict[str, Any]] = []
        for nid in sorted(found, key=self._sort_key):
            payload = self.graph.nodes[nid].with_scope(self.layout)
            payload["hops"] = found[nid]
            results.append(payload)
        return results

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
        """Return one shortest path from ``source_id`` to ``target_id`` if found.

        Args:
            source_id: Start node identifier.
            target_id: End node identifier.
            product: Optional product scope filter.
            project: Optional project scope filter.
            build: Optional build scope filter (with scope inheritance).
            edge_types: Optional edge-type allowlist.
            max_depth: Maximum path length in edges.

        Returns:
            Ordered list of path steps alternating node/edge dicts starting and
            ending with nodes, or ``None`` when no path exists.
        """
        if source_id not in self.graph.nodes or target_id not in self.graph.nodes:
            return None
        if source_id == target_id:
            return [self.graph.nodes[source_id].with_scope(self.layout)]

        allowed = self._allowed_scopes(product=product, project=project, build=build)
        if not self._node_in_scope(source_id, allowed) or not self._node_in_scope(
            target_id, allowed
        ):
            return None

        # BFS: parent[child] = (parent_id, edge)
        parent: dict[str, tuple[str, Any]] = {}
        visited: set[str] = {source_id}
        queue: deque[tuple[str, int]] = deque([(source_id, 0)])
        found = False

        while queue and not found:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for neighbor_id, edge in self.graph.adjacency.get(current, []):
                if not self._edge_allowed(edge.type, edge_types):
                    continue
                if neighbor_id in visited:
                    continue
                if not self._node_in_scope(neighbor_id, allowed):
                    continue
                visited.add(neighbor_id)
                parent[neighbor_id] = (current, edge)
                if neighbor_id == target_id:
                    found = True
                    break
                queue.append((neighbor_id, depth + 1))

        if not found:
            return None

        # Reconstruct node chain then emit node/edge/node/...
        node_chain: list[str] = [target_id]
        cursor = target_id
        while cursor != source_id:
            prev, _edge = parent[cursor]
            node_chain.append(prev)
            cursor = prev
        node_chain.reverse()

        steps: list[dict[str, Any]] = []
        for index, nid in enumerate(node_chain):
            steps.append(self.graph.nodes[nid].with_scope(self.layout))
            if index + 1 < len(node_chain):
                _prev, edge = parent[node_chain[index + 1]]
                steps.append(edge.with_scope(self.layout))
        return steps

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
            product: Optional product filter; ``None`` with no project/build means all.
            project: Optional project filter.
            build: Optional build filter; expands to common/global when enabled.
            node_types: Optional node-type allowlist.

        Returns:
            Matching node records with explicit scope labels, ranked build >
            project common > product common > global.
        """
        allowed = self._allowed_scopes(product=product, project=project, build=build)
        results: list[dict[str, Any]] = []
        for node_id, node in self.graph.nodes.items():
            if node_types is not None and node.type not in node_types:
                continue
            if not self._node_in_scope(node_id, allowed):
                continue
            results.append(node.with_scope(self.layout))
        results.sort(
            key=lambda item: (
                _scope_rank(
                    str(item.get("product", "")),
                    str(item["project"]),
                    str(item["build"]),
                    self.layout,
                ),
                str(item["id"]),
            )
        )
        return results


def open_query(
    graph: KnowledgeGraph,
    *,
    layout: DataLayoutConfig,
    scope_inheritance: bool = True,
) -> GraphQuery:
    """Return a :class:`GraphQuery` bound to ``graph``.

    Args:
        graph: Loaded knowledge graph.
        layout: Path naming configuration.
        scope_inheritance: Whether filters expand like retrieval.

    Returns:
        Query handle.
    """
    return GraphQuery(graph, layout=layout, scope_inheritance=scope_inheritance)


# Re-export for callers that want scope_label without importing models.
__all__ = ["GraphQuery", "open_query", "scope_label"]
