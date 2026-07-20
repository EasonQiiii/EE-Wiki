"""Accumulate knowledge-graph nodes and edges with deduplication."""

from __future__ import annotations

from typing import Any

from ee_wiki.graph.ids import (
    build_node_id,
    case_node_id,
    component_node_id,
    document_node_id,
    net_node_id,
    part_node_id,
    product_node_id,
    project_node_id,
    rail_node_id,
)
from ee_wiki.graph.models import (
    EDGE_APPEARS_IN,
    NODE_BUILD,
    NODE_CASE,
    NODE_COMPONENT,
    NODE_DOCUMENT,
    NODE_NET,
    NODE_PRODUCT,
    NODE_PROJECT,
    NODE_RAIL,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
)


def _edge_key(source: str, target: str, edge_type: str) -> tuple[str, str, str]:
    a, b = sorted((source, target))
    return (a, b, edge_type)


class GraphAssembler:
    """Accumulate nodes/edges with undirected edge deduplication."""

    def __init__(self, source_fingerprints: dict[str, Any] | None = None) -> None:
        self.graph = KnowledgeGraph(source_fingerprints=dict(source_fingerprints or {}))
        self._seen_edges: set[tuple[str, str, str]] = set()

    def add_edge(self, edge: GraphEdge) -> None:
        """Append an edge once (undirected identity on endpoints + type)."""
        key = _edge_key(edge.source, edge.target, edge.type)
        if key in self._seen_edges:
            return
        self._seen_edges.add(key)
        self.graph.add_edge(edge)

    def ensure_scope(self, product: str, project: str, build: str) -> None:
        """Ensure Product, Project, and Build nodes exist with appears_in chain."""
        self.graph.add_node(
            GraphNode(
                id=product_node_id(product),
                type=NODE_PRODUCT,
                product=product,
                project=product,
                build=product,
                attributes={"name": product},
            )
        )
        self.graph.add_node(
            GraphNode(
                id=project_node_id(product, project),
                type=NODE_PROJECT,
                product=product,
                project=project,
                build=project,
                attributes={"name": project},
            )
        )
        self.graph.add_node(
            GraphNode(
                id=build_node_id(product, project, build),
                type=NODE_BUILD,
                product=product,
                project=project,
                build=build,
                attributes={"name": build},
            )
        )
        self.add_edge(
            GraphEdge(
                source=project_node_id(product, project),
                target=product_node_id(product),
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
            )
        )
        self.add_edge(
            GraphEdge(
                source=build_node_id(product, project, build),
                target=project_node_id(product, project),
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
                build=build,
            )
        )

    def ensure_document(
        self,
        *,
        product: str,
        project: str,
        build: str,
        source_file: str,
        document_type: str,
        title: str,
    ) -> GraphNode:
        """Upsert Document + scope and Document → Build appears_in."""
        self.ensure_scope(product, project, build)
        doc = self.graph.add_node(
            GraphNode(
                id=document_node_id(product, project, build, source_file),
                type=NODE_DOCUMENT,
                product=product,
                project=project,
                build=build,
                attributes={
                    "source_file": source_file,
                    "document_type": document_type,
                    "title": title,
                },
            )
        )
        self.add_edge(
            GraphEdge(
                source=doc.id,
                target=build_node_id(product, project, build),
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
                build=build,
            )
        )
        return doc

    def ensure_designator(
        self,
        *,
        product: str,
        project: str,
        build: str,
        designator: str,
        doc_id: str,
        page: int,
    ) -> GraphNode:
        """Upsert a designator Component and Component → Document appears_in."""
        node = self.graph.add_node(
            GraphNode(
                id=component_node_id(product, project, build, designator),
                type=NODE_COMPONENT,
                product=product,
                project=project,
                build=build,
                attributes={
                    "key": designator.strip().upper(),
                    "kind": "designator",
                    "page": page,
                },
            )
        )
        self.add_edge(
            GraphEdge(
                source=node.id,
                target=doc_id,
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
                build=build,
                attributes={"page": page},
            )
        )
        return node

    def ensure_net(
        self,
        *,
        product: str,
        project: str,
        build: str,
        net_name: str,
        doc_id: str,
        page: int,
    ) -> GraphNode:
        """Upsert a Net and Net → Document appears_in."""
        node = self.graph.add_node(
            GraphNode(
                id=net_node_id(product, project, build, net_name),
                type=NODE_NET,
                product=product,
                project=project,
                build=build,
                attributes={"name": net_name.strip().upper(), "page": page},
            )
        )
        self.add_edge(
            GraphEdge(
                source=node.id,
                target=doc_id,
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
                build=build,
                attributes={"page": page},
            )
        )
        return node

    def ensure_part(
        self,
        *,
        part_number: str,
        product: str,
        project: str,
        build: str,
        doc_id: str,
        global_segment: str,
    ) -> GraphNode:
        """Upsert a cross-scope part-number Component and link it to the document.

        Part identity nodes live under the enterprise ``global`` scope so
        scope-inheritance queries always include them; ``appears_in`` edges keep
        the sighting's product/project/build.
        """
        node = self.graph.add_node(
            GraphNode(
                id=part_node_id(part_number),
                type=NODE_COMPONENT,
                product=global_segment,
                project=global_segment,
                build=global_segment,
                attributes={
                    "key": part_number.strip().upper(),
                    "kind": "part_number",
                },
            )
        )
        self.add_edge(
            GraphEdge(
                source=node.id,
                target=doc_id,
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
                build=build,
            )
        )
        return node

    def ensure_case(
        self,
        *,
        product: str,
        project: str,
        build: str,
        case_id: str,
        doc_id: str,
        title: str = "",
        symptom: str = "",
        root_cause: str = "",
        suspected_nets: list[str] | None = None,
        suspected_parts: list[str] | None = None,
        steps: list[str] | None = None,
    ) -> GraphNode:
        """Upsert a Case node and Case → Document appears_in."""
        attributes: dict[str, Any] = {
            "case_id": case_id.strip(),
            "title": title,
        }
        if symptom:
            attributes["symptom"] = symptom
        if root_cause:
            attributes["root_cause"] = root_cause
        if suspected_nets:
            attributes["suspected_nets"] = list(suspected_nets)
        if suspected_parts:
            attributes["suspected_parts"] = list(suspected_parts)
        if steps:
            attributes["steps"] = list(steps)
        node = self.graph.add_node(
            GraphNode(
                id=case_node_id(product, project, build, case_id),
                type=NODE_CASE,
                product=product,
                project=project,
                build=build,
                attributes=attributes,
            )
        )
        self.add_edge(
            GraphEdge(
                source=node.id,
                target=doc_id,
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
                build=build,
            )
        )
        return node

    def ensure_rail(
        self,
        *,
        product: str,
        project: str,
        build: str,
        rail_name: str,
        doc_id: str,
        page: int,
        voltage_hint: str = "",
        role: str = "",
    ) -> GraphNode:
        """Upsert a Rail node and Rail → Document appears_in.

        Args:
            product: Product scope.
            project: Project scope.
            build: Build scope.
            rail_name: Canonical rail / net name (e.g. ``3V3``, ``VBAT``).
            doc_id: Document node id for provenance.
            page: Schematic page where the rail was observed.
            voltage_hint: Optional normalized voltage string (e.g. ``3.3V``).
            role: Optional heuristic role (``input``, ``output``, ``ground``, ``rail``).

        Returns:
            Stored Rail node.
        """
        attributes: dict[str, Any] = {
            "name": rail_name.strip().upper(),
            "page": page,
        }
        if voltage_hint:
            attributes["voltage_hint"] = voltage_hint
        if role:
            attributes["role"] = role
        node = self.graph.add_node(
            GraphNode(
                id=rail_node_id(product, project, build, rail_name),
                type=NODE_RAIL,
                product=product,
                project=project,
                build=build,
                attributes=attributes,
            )
        )
        self.add_edge(
            GraphEdge(
                source=node.id,
                target=doc_id,
                type=EDGE_APPEARS_IN,
                product=product,
                project=project,
                build=build,
                attributes={"page": page},
            )
        )
        return node
