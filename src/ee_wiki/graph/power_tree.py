"""Power-tree query helpers over a loaded knowledge graph (V3 P3).

Answers “what feeds X?”, “what does rail Y power?”, and surfaces conflict /
missing-rail flags. Optional text serialization is for prompts and MCP.
Generation must not import the graph store — callers pass a loaded
:class:`~ee_wiki.graph.query.GraphQuery` or :class:`~ee_wiki.graph.models.KnowledgeGraph`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.graph.ids import (
    component_node_id,
    net_node_id,
    part_node_id,
    rail_node_id,
)
from ee_wiki.graph.models import (
    EDGE_DERIVED_FROM,
    EDGE_SUPPLIES,
    NODE_RAIL,
    KnowledgeGraph,
    scope_label,
)
from ee_wiki.graph.power import is_ground_rail, is_rail_like_net
from ee_wiki.graph.query import GraphQuery
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope

PowerDirection = Literal["feeds", "powers", "tree", "flags"]


@dataclass
class PowerFlag:
    """One power-tree diagnostic flag."""

    code: str
    message: str
    node_ids: list[str] = field(default_factory=list)
    project: str = ""
    build: str = ""
    scope: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API / MCP payloads."""
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "node_ids": list(self.node_ids),
        }
        if self.project:
            payload["project"] = self.project
        if self.build:
            payload["build"] = self.build
        if self.scope:
            payload["scope"] = self.scope
        return payload


class PowerTreeQuery:
    """Directed power-tree queries using ``supplies`` / ``derived_from`` edges."""

    def __init__(self, graph_query: GraphQuery) -> None:
        """Bind to an existing scope-aware :class:`GraphQuery`.

        Args:
            graph_query: Graph query handle (provides graph, layout, scope rules).
        """
        self.graph_query = graph_query
        self.graph: KnowledgeGraph = graph_query.graph
        self.layout: DataLayoutConfig = graph_query.layout

    def _allowed_scopes(
        self,
        *,
        project: str | None,
        build: str | None,
    ) -> set[tuple[str, str]] | None:
        return self.graph_query._allowed_scopes(project=project, build=build)

    def _node_in_scope(
        self,
        node_id: str,
        allowed: set[tuple[str, str]] | None,
    ) -> bool:
        return self.graph_query._node_in_scope(node_id, allowed)

    def resolve(
        self,
        token: str,
        *,
        project: str | None = None,
        build: str | None = None,
    ) -> str | None:
        """Resolve a user token to a graph node id within optional scope.

        Args:
            token: Designator, rail/net name, part number, or full node id.
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

        proj = project or ""
        bld = build or ""
        candidates: list[str] = []
        if proj and bld:
            candidates.extend(
                [
                    rail_node_id(proj, bld, cleaned),
                    net_node_id(proj, bld, cleaned),
                    component_node_id(proj, bld, cleaned),
                ]
            )
        candidates.append(part_node_id(cleaned))

        allowed = self._allowed_scopes(project=project, build=build)
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
        if not matches:
            return None
        # Prefer Rail over Net over Component when multiple match.
        priority = {"Rail": 0, "Net": 1, "Component": 2}
        matches.sort(key=lambda nid: (priority.get(self.graph.nodes[nid].type, 9), nid))
        return matches[0]

    def _directed_neighbors(
        self,
        node_id: str,
        *,
        direction: Literal["in", "out"],
        edge_types: set[str],
        project: str | None,
        build: str | None,
    ) -> list[dict[str, Any]]:
        """Return neighbors reached via directed edges of the given types."""
        if node_id not in self.graph.nodes:
            return []
        allowed = self._allowed_scopes(project=project, build=build)
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        for edge in self.graph.edges:
            if edge.type not in edge_types:
                continue
            if direction == "out":
                if edge.source != node_id:
                    continue
                other = edge.target
            else:
                if edge.target != node_id:
                    continue
                other = edge.source
            if other in seen or other not in self.graph.nodes:
                continue
            if not self._node_in_scope(other, allowed):
                continue
            seen.add(other)
            payload = self.graph.nodes[other].with_scope(self.layout)
            payload["via_edge"] = edge.with_scope(self.layout)
            results.append(payload)

        results.sort(
            key=lambda item: (
                str(item.get("type", "")),
                str(item.get("id", "")),
            )
        )
        return results

    def what_feeds(
        self,
        target: str,
        *,
        project: str | None = None,
        build: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return sources that ``supplies`` / feed into ``target``.

        Args:
            target: Node id or resolvable name (rail, component, net).
            project: Optional project scope.
            build: Optional build scope.

        Returns:
            Neighbor records with ``via_edge`` for each incoming supplies link.
            Also includes parent rails via ``derived_from`` (target derived_from parent).
        """
        node_id = self.resolve(target, project=project, build=build)
        if node_id is None:
            return []
        feeds = self._directed_neighbors(
            node_id,
            direction="in",
            edge_types={EDGE_SUPPLIES},
            project=project,
            build=build,
        )
        parents = self._directed_neighbors(
            node_id,
            direction="out",
            edge_types={EDGE_DERIVED_FROM},
            project=project,
            build=build,
        )
        # Parents of a rail (hierarchy) are also "what feeds" contextually.
        for parent in parents:
            via = parent.get("via_edge") or {}
            if isinstance(via, dict) and via.get("attributes", {}).get("kind") == "rail_of_net":
                continue  # identity link to Net — not a power parent
            parent = dict(parent)
            parent["relation"] = "derived_from"
            feeds.append(parent)
        return feeds

    def what_powers(
        self,
        source: str,
        *,
        project: str | None = None,
        build: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return targets that ``source`` supplies (rails or loads).

        Args:
            source: Regulator, rail, or resolvable name.
            project: Optional project scope.
            build: Optional build scope.

        Returns:
            Neighbor records with ``via_edge`` for each outgoing supplies link.
        """
        node_id = self.resolve(source, project=project, build=build)
        if node_id is None:
            return []
        return self._directed_neighbors(
            node_id,
            direction="out",
            edge_types={EDGE_SUPPLIES},
            project=project,
            build=build,
        )

    def flags(
        self,
        *,
        project: str | None = None,
        build: str | None = None,
    ) -> list[PowerFlag]:
        """Detect conflict / missing-rail issues within scope.

        Flags (heuristic):

        - ``missing_supplier`` — non-ground Rail with no incoming ``supplies``
        - ``orphan_load`` — Component with incoming ``supplies`` from zero rails
          is not flagged; instead Components that look powered only via
          ``connects_to`` a rail-like net without a ``supplies`` edge are noted
          as ``missing_rail_edge`` when a Rail node exists for that net
        - ``multi_supplier`` — Rail with multiple distinct regulator suppliers

        Args:
            project: Optional project filter.
            build: Optional build filter.

        Returns:
            List of :class:`PowerFlag` diagnostics.
        """
        allowed = self._allowed_scopes(project=project, build=build)
        flags: list[PowerFlag] = []

        rails = [
            node
            for node_id, node in self.graph.nodes.items()
            if node.type == NODE_RAIL
            and self._node_in_scope(node_id, allowed)
            and not is_ground_rail(str(node.attributes.get("name", "")))
        ]

        for rail in rails:
            suppliers = [
                e
                for e in self.graph.edges
                if e.type == EDGE_SUPPLIES and e.target == rail.id
            ]
            if not suppliers:
                flags.append(
                    PowerFlag(
                        code="missing_supplier",
                        message=(
                            f"Rail {rail.attributes.get('name', rail.id)} has no "
                            "incoming supplies edge (regulator unknown or not extracted)"
                        ),
                        node_ids=[rail.id],
                        project=rail.project,
                        build=rail.build,
                        scope=scope_label(rail.project, rail.build, self.layout),
                    )
                )
            else:
                sources = {e.source for e in suppliers}
                if len(sources) > 1:
                    flags.append(
                        PowerFlag(
                            code="multi_supplier",
                            message=(
                                f"Rail {rail.attributes.get('name', rail.id)} has "
                                f"{len(sources)} supplier sources (possible conflict)"
                            ),
                            node_ids=[rail.id, *sorted(sources)],
                            project=rail.project,
                            build=rail.build,
                            scope=scope_label(rail.project, rail.build, self.layout),
                        )
                    )

            # Orphan hierarchy: output rail with no derived_from parent when
            # other rails exist in the same build.
            hierarchy_parents = [
                e
                for e in self.graph.edges
                if e.type == EDGE_DERIVED_FROM
                and e.source == rail.id
                and (e.attributes or {}).get("kind") == "rail_hierarchy"
            ]
            sibling_rails = [
                r
                for r in rails
                if r.project == rail.project
                and r.build == rail.build
                and r.id != rail.id
            ]
            if (
                sibling_rails
                and not hierarchy_parents
                and rail.attributes.get("role") == "output"
            ):
                flags.append(
                    PowerFlag(
                        code="missing_parent_rail",
                        message=(
                            f"Output rail {rail.attributes.get('name', rail.id)} has no "
                            "derived_from parent rail (input rail unknown)"
                        ),
                        node_ids=[rail.id],
                        project=rail.project,
                        build=rail.build,
                        scope=scope_label(rail.project, rail.build, self.layout),
                    )
                )

        return flags

    def serialize_tree(
        self,
        root: str,
        *,
        project: str | None = None,
        build: str | None = None,
        max_depth: int = 4,
    ) -> str:
        """Serialize a simple indented power tree rooted at ``root``.

        Walks outgoing ``supplies`` edges and child rails that ``derived_from``
        this root (inverse hierarchy). Suitable for prompt / MCP text.

        Args:
            root: Rail, regulator, or resolvable name.
            project: Optional project scope.
            build: Optional build scope.
            max_depth: Maximum tree depth.

        Returns:
            Multi-line text tree, or a short message when root is unresolved.
        """
        node_id = self.resolve(root, project=project, build=build)
        if node_id is None:
            return f"(unresolved power root: {root!r})"

        lines: list[str] = []
        visited: set[str] = set()

        def label(nid: str) -> str:
            node = self.graph.nodes[nid]
            attrs = node.attributes or {}
            name = attrs.get("name") or attrs.get("key") or nid
            role = attrs.get("role")
            extra = f" [{role}]" if role else ""
            return f"{node.type}:{name}{extra}"

        def walk(nid: str, depth: int) -> None:
            if depth > max_depth or nid in visited:
                return
            visited.add(nid)
            indent = "  " * depth
            lines.append(f"{indent}{label(nid)}")
            # Children powered by this node
            for edge in self.graph.edges:
                if edge.type == EDGE_SUPPLIES and edge.source == nid:
                    if edge.target not in visited:
                        walk(edge.target, depth + 1)
                # Child rails that derive from this rail (hierarchy inverse)
                if (
                    edge.type == EDGE_DERIVED_FROM
                    and edge.target == nid
                    and (edge.attributes or {}).get("kind") == "rail_hierarchy"
                ):
                    if edge.source not in visited:
                        walk(edge.source, depth + 1)

        walk(node_id, 0)
        return "\n".join(lines) if lines else label(node_id)

    def query(
        self,
        q: str,
        *,
        direction: PowerDirection = "tree",
        project: str | None = None,
        build: str | None = None,
        max_depth: int = 4,
    ) -> dict[str, Any]:
        """Unified power-tree query for HTTP / MCP.

        Args:
            q: Entity name, designator, or node id (ignored for ``flags``).
            direction: ``feeds`` | ``powers`` | ``tree`` | ``flags``.
            project: Optional project filter.
            build: Optional build filter.
            max_depth: Tree serialization depth.

        Returns:
            JSON-serializable result dict with ``direction``, ``query``, and
            either ``hits``, ``tree``, or ``flags``.
        """
        base: dict[str, Any] = {
            "query": q,
            "direction": direction,
            "project": project,
            "build": build,
            "limitations": (
                "Heuristic power tree from schematic co-occurrence and datasheet "
                "supply_voltage — not a CAD netlist. Treat edges as candidates."
            ),
        }
        if direction == "flags":
            base["flags"] = [
                flag.to_dict()
                for flag in self.flags(project=project, build=build)
            ]
            return base

        resolved = self.resolve(q, project=project, build=build)
        base["resolved_id"] = resolved
        if resolved is None:
            base["hits"] = []
            base["tree"] = f"(unresolved power root: {q!r})"
            return base

        if direction == "feeds":
            base["hits"] = self.what_feeds(resolved, project=project, build=build)
        elif direction == "powers":
            base["hits"] = self.what_powers(resolved, project=project, build=build)
        else:
            base["tree"] = self.serialize_tree(
                resolved,
                project=project,
                build=build,
                max_depth=max_depth,
            )
            base["hits"] = self.what_powers(resolved, project=project, build=build)
            base["feeds"] = self.what_feeds(resolved, project=project, build=build)
        return base


def open_power_query(graph_query: GraphQuery) -> PowerTreeQuery:
    """Return a :class:`PowerTreeQuery` bound to ``graph_query``.

    Args:
        graph_query: Scope-aware graph query handle.

    Returns:
        Power-tree query helper.
    """
    return PowerTreeQuery(graph_query)


def list_rails(
    graph: KnowledgeGraph,
    *,
    layout: DataLayoutConfig,
    project: str | None = None,
    build: str | None = None,
    scope_inheritance: bool = True,
) -> list[dict[str, Any]]:
    """List Rail nodes in scope (convenience for inventory).

    Args:
        graph: Loaded knowledge graph.
        layout: Path naming configuration.
        project: Optional project filter.
        build: Optional build filter.
        scope_inheritance: Expand like retrieval when true.

    Returns:
        Rail node dicts with scope labels.
    """
    allowed: set[tuple[str, str]] | None = None
    if project or build:
        proj = project or layout.enterprise_project
        bld = build or layout.project_shared_build
        if scope_inheritance:
            allowed = set(expand_retrieval_scope(proj, bld, layout))
        else:
            allowed = {(proj, bld)}

    results: list[dict[str, Any]] = []
    for node in graph.nodes.values():
        if node.type != NODE_RAIL:
            continue
        if allowed is not None and (node.project, node.build) not in allowed:
            continue
        if is_ground_rail(str(node.attributes.get("name", ""))):
            continue
        if not is_rail_like_net(str(node.attributes.get("name", node.id))):
            continue
        results.append(node.with_scope(layout))
    results.sort(key=lambda item: str(item.get("id", "")))
    return results
