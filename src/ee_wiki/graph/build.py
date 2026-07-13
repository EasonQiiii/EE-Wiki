"""Build a knowledge graph from indexed chunks, components, and debug cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ee_wiki.common.config import AppConfig
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE, chunk_from_dict
from ee_wiki.common.types import Chunk, DataLayoutConfig
from ee_wiki.graph.assemble import GraphAssembler
from ee_wiki.graph.models import (
    EDGE_CAUSED_BY,
    EDGE_CONNECTS_TO,
    EDGE_MENTIONS,
    EDGE_RELATED_TO,
    EDGE_SAME_AS,
    GraphEdge,
    KnowledgeGraph,
)
from ee_wiki.graph.power import add_power_semantics
from ee_wiki.graph.store import GraphManifest, GraphStoreError, JsonlGraphStore
from ee_wiki.ingestion.keywords import is_designator, is_part_number_keyword
from ee_wiki.knowledge.indexer.case_index import CaseIndex, load_case_index
from ee_wiki.knowledge.indexer.component_index import (
    ComponentIndex,
    load_component_index,
)
from ee_wiki.knowledge.indexer.store import CHUNKS_NAME, MANIFEST_NAME

logger = get_logger(__name__)


class GraphBuildError(EEWikiError):
    """Failed to build a knowledge graph from index artifacts."""


@dataclass(frozen=True)
class GraphBuildResult:
    """Outcome of a graph build run."""

    manifest: GraphManifest
    node_count: int
    edge_count: int
    graph_dir: Path


def _designators_from_chunk(chunk: Chunk) -> list[str]:
    meta = chunk.metadata
    if meta.document_type != SCHEMATIC_DOCUMENT_TYPE or not meta.major_components:
        return []
    return [t for t in meta.major_components if is_designator(t)]


def _nets_from_chunk(chunk: Chunk) -> list[str]:
    meta = chunk.metadata
    if meta.document_type != SCHEMATIC_DOCUMENT_TYPE or not meta.nets:
        return []
    return [n for n in meta.nets if n and str(n).strip()]


def _part_numbers_from_chunk(chunk: Chunk) -> list[str]:
    return [t for t in chunk.metadata.keywords if is_part_number_keyword(t)]


def _add_cases_to_graph(
    asm: GraphAssembler,
    case_index: CaseIndex,
    *,
    enterprise_project: str,
) -> None:
    """Add Case nodes and mentions / caused_by / related_to edges."""
    for record in case_index.cases:
        if not record.case_id or not record.source_file:
            continue
        doc = asm.ensure_document(
            project=record.project,
            build=record.build,
            source_file=record.source_file,
            document_type=record.document_type,
            title=record.title,
        )
        case_node = asm.ensure_case(
            project=record.project,
            build=record.build,
            case_id=record.case_id,
            doc_id=doc.id,
            title=record.title,
            symptom=record.symptom,
            root_cause=record.root_cause,
            suspected_nets=list(record.suspected_nets),
            suspected_parts=list(record.suspected_parts),
            steps=list(record.steps),
        )

        for net_name in record.suspected_nets:
            net = asm.ensure_net(
                project=record.project,
                build=record.build,
                net_name=net_name,
                doc_id=doc.id,
                page=0,
            )
            asm.add_edge(
                GraphEdge(
                    source=case_node.id,
                    target=net.id,
                    type=EDGE_MENTIONS,
                    project=record.project,
                    build=record.build,
                )
            )

        for part in record.suspected_parts:
            cleaned = part.strip()
            if not cleaned:
                continue
            if is_designator(cleaned):
                target = asm.ensure_designator(
                    project=record.project,
                    build=record.build,
                    designator=cleaned,
                    doc_id=doc.id,
                    page=0,
                )
            else:
                target = asm.ensure_part(
                    part_number=cleaned,
                    project=record.project,
                    build=record.build,
                    doc_id=doc.id,
                    enterprise_project=enterprise_project,
                )
            asm.add_edge(
                GraphEdge(
                    source=case_node.id,
                    target=target.id,
                    type=EDGE_MENTIONS,
                    project=record.project,
                    build=record.build,
                )
            )

        # Root-cause text may name a designator or part — link via caused_by
        if record.root_cause:
            cause_tokens = [
                token
                for token in record.root_cause.replace(",", " ").split()
                if is_designator(token) or is_part_number_keyword(token)
            ]
            for token in cause_tokens:
                if is_designator(token):
                    target = asm.ensure_designator(
                        project=record.project,
                        build=record.build,
                        designator=token,
                        doc_id=doc.id,
                        page=0,
                    )
                else:
                    target = asm.ensure_part(
                        part_number=token,
                        project=record.project,
                        build=record.build,
                        doc_id=doc.id,
                        enterprise_project=enterprise_project,
                    )
                asm.add_edge(
                    GraphEdge(
                        source=case_node.id,
                        target=target.id,
                        type=EDGE_CAUSED_BY,
                        project=record.project,
                        build=record.build,
                    )
                )

        for citation in record.case_citations:
            cite_path = citation.strip()
            if not cite_path:
                continue
            # Citation may be a relative path; still create a Document node under
            # the case's project/build so related_to remains queryable.
            related = asm.ensure_document(
                project=record.project,
                build=record.build,
                source_file=cite_path,
                document_type="",
                title=Path(cite_path).stem,
            )
            asm.add_edge(
                GraphEdge(
                    source=case_node.id,
                    target=related.id,
                    type=EDGE_RELATED_TO,
                    project=record.project,
                    build=record.build,
                )
            )


def build_graph_from_chunks(
    chunks: list[Chunk],
    *,
    layout: DataLayoutConfig,
    component_index: ComponentIndex | None = None,
    case_index: CaseIndex | None = None,
    source_fingerprints: dict[str, Any] | None = None,
    power_tree: bool = True,
) -> KnowledgeGraph:
    """Build an in-memory knowledge graph from indexed chunks.

    Derives Component / Net / Document / Project / Build nodes from chunk
    metadata and schematic page fields. Adds ``connects_to`` (component↔net
    co-occurrence on a page), ``appears_in``, and ``same_as`` (designator↔part).
    When ``case_index`` is provided, also adds Case nodes with ``mentions``,
    ``caused_by``, and ``related_to`` edges. When ``power_tree`` is true,
    extracts Rail nodes and ``supplies`` / ``derived_from`` edges (V3 P3).

    Args:
        chunks: Indexed retrieval chunks (typically from ``chunks.jsonl``).
        layout: Path naming configuration (enterprise segment for part nodes).
        component_index: Optional ``components.json`` for extra part keys.
        case_index: Optional ``cases.json`` for debug-case nodes.
        source_fingerprints: Optional fingerprints copied into the manifest.
        power_tree: When true, run heuristic power-tree extraction.

    Returns:
        Populated :class:`KnowledgeGraph`.
    """
    asm = GraphAssembler(source_fingerprints)
    enterprise = layout.enterprise_project

    if component_index is not None:
        for key, hits in component_index.entries.items():
            for hit in hits:
                doc = asm.ensure_document(
                    project=hit.project,
                    build=hit.build,
                    source_file=hit.source_file,
                    document_type=hit.document_type,
                    title=hit.title,
                )
                if hit.kind == "designator":
                    asm.ensure_designator(
                        project=hit.project,
                        build=hit.build,
                        designator=key,
                        doc_id=doc.id,
                        page=hit.page,
                    )
                else:
                    asm.ensure_part(
                        part_number=key,
                        project=hit.project,
                        build=hit.build,
                        doc_id=doc.id,
                        enterprise_project=enterprise,
                    )

    for chunk in chunks:
        meta = chunk.metadata
        if not meta.project or not meta.source_file:
            continue
        doc = asm.ensure_document(
            project=meta.project,
            build=meta.build,
            source_file=meta.source_file,
            document_type=meta.document_type,
            title=meta.title,
        )
        page = chunk.citation.page or meta.page

        designators = _designators_from_chunk(chunk)
        nets = _nets_from_chunk(chunk)
        parts = _part_numbers_from_chunk(chunk)

        component_nodes = [
            asm.ensure_designator(
                project=meta.project,
                build=meta.build,
                designator=designator,
                doc_id=doc.id,
                page=page,
            )
            for designator in designators
        ]
        net_nodes = [
            asm.ensure_net(
                project=meta.project,
                build=meta.build,
                net_name=net_name,
                doc_id=doc.id,
                page=page,
            )
            for net_name in nets
        ]
        part_nodes = [
            asm.ensure_part(
                part_number=part,
                project=meta.project,
                build=meta.build,
                doc_id=doc.id,
                enterprise_project=enterprise,
            )
            for part in parts
        ]

        for component in component_nodes:
            for net in net_nodes:
                asm.add_edge(
                    GraphEdge(
                        source=component.id,
                        target=net.id,
                        type=EDGE_CONNECTS_TO,
                        project=meta.project,
                        build=meta.build,
                        attributes={"page": page},
                    )
                )

        for component in component_nodes:
            for part in part_nodes:
                asm.add_edge(
                    GraphEdge(
                        source=component.id,
                        target=part.id,
                        type=EDGE_SAME_AS,
                        project=meta.project,
                        build=meta.build,
                    )
                )

    if case_index is not None:
        _add_cases_to_graph(asm, case_index, enterprise_project=enterprise)

    power_stats = None
    if power_tree:
        power_stats = add_power_semantics(
            asm,
            chunks,
            enterprise_project=enterprise,
        )
        if power_stats is not None:
            asm.graph.source_fingerprints = {
                **asm.graph.source_fingerprints,
                "power_rails": power_stats.rails,
                "power_supplies_edges": power_stats.supplies_edges,
                "power_derived_from_edges": power_stats.derived_from_edges,
            }

    logger.info(
        "Built knowledge graph: %d node(s), %d edge(s) from %d chunk(s)",
        len(asm.graph.nodes),
        len(asm.graph.edges),
        len(chunks),
    )
    return asm.graph


def load_chunks_from_index(indexes_dir: Path) -> tuple[list[Chunk], dict[str, Any]]:
    """Load chunks and source fingerprints without requiring embeddings.

    Args:
        indexes_dir: Hybrid index directory (``data/indexes/``).

    Returns:
        ``(chunks, source_fingerprints)``.

    Raises:
        GraphBuildError: If the index chunks file is missing or corrupt.
    """
    chunks_path = indexes_dir.resolve() / CHUNKS_NAME
    manifest_path = indexes_dir.resolve() / MANIFEST_NAME
    if not chunks_path.is_file():
        raise GraphBuildError(f"Index chunks not found: {chunks_path}")

    fingerprints: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            fingerprints = dict(manifest_data.get("source_fingerprints", {}))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("Could not read index manifest fingerprints: %s", exc)

    try:
        chunks: list[Chunk] = []
        with chunks_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    chunks.append(chunk_from_dict(json.loads(line)))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise GraphBuildError(f"Failed to load chunks from {chunks_path}") from exc

    return chunks, fingerprints


def build_and_save_graph(config: AppConfig) -> GraphBuildResult:
    """Build the knowledge graph from the current index and save to ``graph_dir``.

    Args:
        config: Loaded application configuration.

    Returns:
        Build result with manifest and counts.

    Raises:
        GraphBuildError: If index artifacts are missing.
        GraphStoreError: If persistence fails.
    """
    chunks, fingerprints = load_chunks_from_index(config.indexes_dir)
    component_index = load_component_index(config.indexes_dir)
    case_index = load_case_index(config.indexes_dir)
    graph = build_graph_from_chunks(
        chunks,
        layout=config.data_layout,
        component_index=component_index,
        case_index=case_index,
        power_tree=config.graph.power_tree,
        source_fingerprints={
            "index_documents": len(fingerprints),
            "chunk_count": len(chunks),
            "components_present": component_index is not None,
            "cases_present": case_index is not None,
            "case_count": len(case_index.cases) if case_index is not None else 0,
            "power_tree": config.graph.power_tree,
        },
    )
    store = JsonlGraphStore()
    try:
        manifest = store.save_graph(config.graph_dir, graph=graph)
    except GraphStoreError:
        raise
    return GraphBuildResult(
        manifest=manifest,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        graph_dir=config.graph_dir,
    )
