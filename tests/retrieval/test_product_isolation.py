"""Cross-product leakage regression (ADR 0011).

Two products sharing identical ``project`` + ``build`` slugs
(``iphone/logan/p1`` vs ``pencil/logan/p1``) must never return the other
product's hits from retrieval, case/component indexes, graph, connectivity,
rules, ToolBus, or scoped API filters.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient

from ee_wiki.api.app import create_app
from ee_wiki.api.deps import get_config, get_rag_service
from ee_wiki.common.types import Chunk, Citation, DataLayoutConfig, Metadata
from ee_wiki.connectivity.query import ConnectivityQuery
from ee_wiki.connectivity.store import load_connectivity_documents
from ee_wiki.graph import build_graph_from_chunks, open_query
from ee_wiki.graph.ids import component_node_id, net_node_id
from ee_wiki.graph.models import NODE_COMPONENT, NODE_NET
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionManifest,
    PinNetBinding,
    SchematicConnectivity,
)
from ee_wiki.knowledge.indexer.case_index import CaseIndex, DebugCaseRecord, build_case_index
from ee_wiki.knowledge.indexer.component_index import ComponentHit, ComponentIndex
from ee_wiki.retrieval.case_lookup import lookup_case_chunk_ids, search_cases
from ee_wiki.retrieval.component_lookup import lookup_tokens, search_components
from ee_wiki.retrieval.hybrid.engine import HybridChunk, HybridRagEngine
from ee_wiki.rules.engine import open_rule_engine
from ee_wiki.tools.bus import ToolBus
from ee_wiki.tools.scope import ScopeEnvelope

IPHONE = "iphone"
PENCIL = "pencil"
PROJECT = "logan"
BUILD = "p1"


def _layout(tmp_path: Path) -> DataLayoutConfig:
    return DataLayoutConfig(
        enterprise_project="global",
        project_shared_build="common",
        document_type_folders={
            "sch": "schematic",
            "note": "engineering_note",
            "fa": "failure_analysis",
        },
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
    )


def _chunk(
    *,
    chunk_id: str,
    product: str,
    content: str,
    document_type: str = "engineering_note",
    major_components: list[str] | None = None,
    nets: list[str] | None = None,
) -> Chunk:
    folder = "sch" if document_type == "schematic" else "note"
    source = f"data/raw/{product}/{PROJECT}/{BUILD}/{folder}/{chunk_id}.md"
    return Chunk(
        chunk_id=chunk_id,
        content=content,
        metadata=Metadata(
            product=product,
            project=PROJECT,
            build=BUILD,
            document_type=document_type,
            title=chunk_id,
            source_file=source,
            target_file=source.replace("/raw/", "/processed/"),
            major_components=major_components or [],
            nets=nets or [],
        ),
        citation=Citation(source_file=source, chunk_id=chunk_id, excerpt=content[:80]),
    )


def _hybrid(chunk: Chunk, embedding: np.ndarray) -> HybridChunk:
    return HybridChunk(
        chunk_id=chunk.chunk_id,
        content=chunk.content,
        metadata={
            "product": chunk.metadata.product,
            "project": chunk.metadata.project,
            "build": chunk.metadata.build,
            "document_type": chunk.metadata.document_type,
        },
        citation={
            "source_file": chunk.citation.source_file,
            "chunk_id": chunk.citation.chunk_id,
            "excerpt": chunk.citation.excerpt,
        },
        embedding=embedding,
    )


def _mock_rerank_logits(model: MagicMock, values: list[float]) -> None:
    logits = model.return_value.logits.view.return_value.float.return_value.cpu.return_value.numpy
    logits.return_value = np.array(values)


@pytest.fixture
def dual_product_engine(app_config) -> HybridRagEngine:
    """Engine indexed with twin logan/p1 chunks under iphone and pencil."""
    iphone = _chunk(
        chunk_id="iphone_note",
        product=IPHONE,
        content="IPHONE_LOGAN_P1_MARKER VBAT rail for iphone logan.",
    )
    pencil = _chunk(
        chunk_id="pencil_note",
        product=PENCIL,
        content="PENCIL_LOGAN_P1_SECRET VBAT rail for pencil logan.",
    )
    chunks = [iphone, pencil]
    embeddings = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)

    engine = HybridRagEngine(app_config)
    engine.knowledge_base = [
        _hybrid(chunk, embeddings[i]) for i, chunk in enumerate(chunks)
    ]
    engine._chunk_positions = {
        chunk.chunk_id: i for i, chunk in enumerate(engine.knowledge_base)
    }
    engine.bm25 = MagicMock()
    engine.bm25.get_scores.return_value = [0.9, 0.9]

    mock_embed = MagicMock()
    mock_embed.encode.return_value = np.array([1.0, 0.0], dtype=np.float32)
    engine._embed_model = mock_embed

    mock_reranker = MagicMock()
    _mock_rerank_logits(mock_reranker, [0.9, 0.9])
    tokenizer_batch = {"input_ids": MagicMock(), "attention_mask": MagicMock()}
    tokenizer_output = MagicMock()
    tokenizer_output.to.return_value = tokenizer_batch
    engine._rerank_tokenizer = MagicMock(return_value=tokenizer_output)
    engine._rerank_model = mock_reranker
    return engine


def test_hybrid_retrieve_excludes_other_product_same_slugs(
    dual_product_engine: HybridRagEngine,
) -> None:
    results = dual_product_engine.retrieve(
        "VBAT rail",
        target_product=IPHONE,
        target_project=PROJECT,
        target_build=BUILD,
        top_k_final=5,
    )
    ids = {c.chunk_id for c in results.chunks}
    assert "iphone_note" in ids
    assert "pencil_note" not in ids
    assert all(c.metadata.get("product") == IPHONE for c in results.chunks)


def test_hybrid_retrieve_pencil_excludes_iphone(
    dual_product_engine: HybridRagEngine,
) -> None:
    results = dual_product_engine.retrieve(
        "VBAT rail",
        target_product=PENCIL,
        target_project=PROJECT,
        target_build=BUILD,
        top_k_final=5,
    )
    ids = {c.chunk_id for c in results.chunks}
    assert "pencil_note" in ids
    assert "iphone_note" not in ids


def test_case_lookup_excludes_other_product(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    index = build_case_index(
        [
            Chunk(
                chunk_id="iphone_fa",
                content="No boot iphone",
                metadata=Metadata(
                    product=IPHONE,
                    project=PROJECT,
                    build=BUILD,
                    document_type="failure_analysis",
                    title="iphone rma",
                    source_file=f"data/raw/{IPHONE}/{PROJECT}/{BUILD}/fa/rma.md",
                    case_id="RMA-IPHONE",
                    symptom="No boot",
                    suspected_parts=["U101"],
                    suspected_nets=["NET_VCC"],
                ),
                citation=Citation(
                    source_file=f"data/raw/{IPHONE}/{PROJECT}/{BUILD}/fa/rma.md",
                    chunk_id="iphone_fa",
                    excerpt="No boot",
                ),
            ),
            Chunk(
                chunk_id="pencil_fa",
                content="No boot pencil",
                metadata=Metadata(
                    product=PENCIL,
                    project=PROJECT,
                    build=BUILD,
                    document_type="failure_analysis",
                    title="pencil rma",
                    source_file=f"data/raw/{PENCIL}/{PROJECT}/{BUILD}/fa/rma.md",
                    case_id="RMA-PENCIL",
                    symptom="No boot",
                    suspected_parts=["U101"],
                    suspected_nets=["NET_VCC"],
                ),
                citation=Citation(
                    source_file=f"data/raw/{PENCIL}/{PROJECT}/{BUILD}/fa/rma.md",
                    chunk_id="pencil_fa",
                    excerpt="No boot",
                ),
            ),
        ]
    )
    matched = lookup_case_chunk_ids(
        index,
        ["NO", "BOOT", "U101"],
        layout=layout,
        target_product=IPHONE,
        target_project=PROJECT,
        target_build=BUILD,
        scope_inheritance=True,
    )
    assert matched == {"iphone_fa"}

    hits = search_cases(
        index,
        "No boot U101",
        layout=layout,
        target_product=IPHONE,
        target_project=PROJECT,
        target_build=BUILD,
    )
    assert {h.case_id for h in hits} == {"RMA-IPHONE"}


def test_component_lookup_excludes_other_product(app_config) -> None:
    index = ComponentIndex(
        version=1,
        built_at="2026-01-01T00:00:00Z",
        entries={
            "U101": [
                ComponentHit(
                    key="U101",
                    kind="designator",
                    chunk_id="iphone_sch",
                    product=IPHONE,
                    project=PROJECT,
                    build=BUILD,
                    document_type="schematic",
                    source_file=f"data/raw/{IPHONE}/{PROJECT}/{BUILD}/sch/board.pdf",
                    page=1,
                    title="iphone board",
                    excerpt="U101 PHY iphone",
                ),
                ComponentHit(
                    key="U101",
                    kind="designator",
                    chunk_id="pencil_sch",
                    product=PENCIL,
                    project=PROJECT,
                    build=BUILD,
                    document_type="schematic",
                    source_file=f"data/raw/{PENCIL}/{PROJECT}/{BUILD}/sch/board.pdf",
                    page=1,
                    title="pencil board",
                    excerpt="U101 PHY pencil",
                ),
            ],
        },
    )
    chunk_ids = lookup_tokens(
        index,
        ["U101"],
        layout=app_config.data_layout,
        target_product=IPHONE,
        target_project=PROJECT,
        target_build=BUILD,
        scope_inheritance=True,
    )
    assert chunk_ids == {"iphone_sch"}

    hits = search_components(
        index,
        "U101",
        layout=app_config.data_layout,
        target_product=IPHONE,
        target_project=PROJECT,
        target_build=BUILD,
    )
    assert {h.chunk_id for h in hits} == {"iphone_sch"}
    assert all(h.product == IPHONE for h in hits)


def test_graph_ids_and_filter_isolate_products(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _chunk(
            chunk_id="iphone_sch",
            product=IPHONE,
            content="schematic",
            document_type="schematic",
            major_components=["U101"],
            nets=["NET_VCC"],
        ),
        _chunk(
            chunk_id="pencil_sch",
            product=PENCIL,
            content="schematic",
            document_type="schematic",
            major_components=["U101"],
            nets=["NET_VCC"],
        ),
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=False)
    iphone_u101 = component_node_id(IPHONE, PROJECT, BUILD, "U101")
    pencil_u101 = component_node_id(PENCIL, PROJECT, BUILD, "U101")
    assert iphone_u101 != pencil_u101
    assert iphone_u101 == f"component:{IPHONE}/{PROJECT}/{BUILD}:U101"

    query = open_query(graph, layout=layout, scope_inheritance=True)
    nodes = query.filter_by_scope(
        product=IPHONE,
        project=PROJECT,
        build=BUILD,
        node_types=[NODE_COMPONENT, NODE_NET],
    )
    ids = {n["id"] for n in nodes}
    assert iphone_u101 in ids
    assert pencil_u101 not in ids
    assert net_node_id(IPHONE, PROJECT, BUILD, "NET_VCC") in ids
    assert net_node_id(PENCIL, PROJECT, BUILD, "NET_VCC") not in ids


def _write_connectivity_sidecar(path: Path, product: str, net_name: str) -> None:
    connectivity = SchematicConnectivity(
        source_file=f"data/raw/{product}/{PROJECT}/{BUILD}/sch/board.pdf",
        companions=CompanionManifest(boardview="board.brd"),
        sources_used=["boardview"],
        nets={
            net_name: [
                PinNetBinding("U1", "1", net_name, "boardview"),
            ],
        },
        parts={"U1": [PinNetBinding("U1", "1", net_name, "boardview")]},
        pages=[],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(connectivity.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_connectivity_load_and_trace_isolate_products(tmp_path: Path) -> None:
    processed = tmp_path / "processed"
    _write_connectivity_sidecar(
        processed / IPHONE / PROJECT / BUILD / "sch" / "board.connectivity.json",
        IPHONE,
        "IPHONE_ONLY_NET",
    )
    _write_connectivity_sidecar(
        processed / PENCIL / PROJECT / BUILD / "sch" / "board.connectivity.json",
        PENCIL,
        "PENCIL_ONLY_NET",
    )
    layout = _layout(tmp_path)
    layout = DataLayoutConfig(
        enterprise_project=layout.enterprise_project,
        project_shared_build=layout.project_shared_build,
        document_type_folders=layout.document_type_folders,
        raw_dir=tmp_path / "raw",
        processed_dir=processed,
    )

    docs = load_connectivity_documents(
        processed, layout, product=IPHONE, project=PROJECT, build=BUILD
    )
    assert len(docs) == 1
    assert docs[0].product == IPHONE

    cq = ConnectivityQuery(documents=docs, layout=layout)
    hit = cq.trace_net("IPHONE_ONLY_NET", product=IPHONE, project=PROJECT, build=BUILD)
    assert hit["found"] is True
    miss = cq.trace_net("PENCIL_ONLY_NET", product=IPHONE, project=PROJECT, build=BUILD)
    assert miss["found"] is False


def test_rules_fa_recurrence_does_not_mix_products(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    chunks = [
        _chunk(
            chunk_id="iphone_sch",
            product=IPHONE,
            content="schematic",
            document_type="schematic",
            major_components=["U1"],
            nets=["NET_A"],
        )
    ]
    graph = build_graph_from_chunks(chunks, layout=layout, power_tree=False)
    gq = open_query(graph, layout=layout)
    cases = CaseIndex(
        version=1,
        built_at="2026-01-01T00:00:00Z",
        cases=(
            DebugCaseRecord(
                case_id="RMA-IPHONE-1",
                product=IPHONE,
                project=PROJECT,
                build="p1",
                title="No boot p1",
                source_file=f"{IPHONE}/{PROJECT}/p1/fa/rma1.md",
                document_type="failure_analysis",
                symptom="No boot",
                suspected_parts=("U101",),
                chunk_ids=("fa1",),
            ),
            DebugCaseRecord(
                case_id="RMA-PENCIL-1",
                product=PENCIL,
                project=PROJECT,
                build="p2",
                title="No boot pencil",
                source_file=f"{PENCIL}/{PROJECT}/p2/fa/rma1.md",
                document_type="failure_analysis",
                symptom="No boot",
                suspected_parts=("U101",),
                chunk_ids=("fa2",),
            ),
        ),
    )
    pack_dir = tmp_path / "rules"
    pack_dir.mkdir()
    (pack_dir / "fa_recurrence.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "fa_recurrence",
                "name": "FA recurrence",
                "description": "test",
                "check": {"type": "fa_recurrence", "params": {"min_builds": 2}},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    engine = open_rule_engine(gq, pack_dir, case_index=cases)
    result = engine.evaluate(
        rule_ids=["fa_recurrence"], product=IPHONE, project=PROJECT
    )[0]
    # Only one iphone build has the symptom — pencil p2 must not count as recurrence.
    assert result.status == "pass"
    assert PENCIL not in (result.message or "")
    for citation in result.citations:
        assert citation.product != PENCIL


def test_toolbus_scope_envelope_clamps_cross_product(tmp_path: Path) -> None:
    ctx = MagicMock()
    ctx.config.agents.tool_timeout_seconds = 60.0
    ctx.config.agents.max_concurrent_tools = 2

    captured: dict = {}

    def fake_search(_ctx, args):
        captured.update(args)
        return json.dumps({"ok": True, "product": args.get("product")})

    bus = ToolBus(ctx, span_log=tmp_path / "spans.jsonl")
    bus._registry["engineering_search"] = fake_search

    result = bus.call(
        "engineering_search",
        {
            "query": "U101",
            "product": PENCIL,
            "project": PROJECT,
            "build": BUILD,
        },
        caller_id="hw",
        scope=ScopeEnvelope(product=IPHONE, project=PROJECT, build=BUILD),
    )
    assert result.ok is True
    assert captured["product"] == IPHONE
    assert captured["project"] == PROJECT
    assert captured["build"] == BUILD


def test_api_components_search_requires_product_when_project_set(
    app_config,
) -> None:
    service = MagicMock()
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: app_config
    client = TestClient(app)

    response = client.get(
        "/v1/components/search",
        params={"q": "U101", "project": PROJECT, "build": BUILD},
    )
    assert response.status_code == 400
    service.engine.search_components.assert_not_called()


def test_api_components_search_passes_product_scope(app_config) -> None:
    service = MagicMock()
    service.engine.search_components.return_value = [
        ComponentHit(
            key="U101",
            kind="designator",
            chunk_id="iphone_sch",
            product=IPHONE,
            project=PROJECT,
            build=BUILD,
            document_type="schematic",
            source_file=f"data/raw/{IPHONE}/{PROJECT}/{BUILD}/sch/board.pdf",
            page=1,
            title="board",
            excerpt="U101",
        )
    ]
    app = create_app()
    app.dependency_overrides[get_rag_service] = lambda: service
    app.dependency_overrides[get_config] = lambda: app_config
    client = TestClient(app)

    response = client.get(
        "/v1/components/search",
        params={
            "q": "U101",
            "product": IPHONE,
            "project": PROJECT,
            "build": BUILD,
        },
    )
    assert response.status_code == 200
    kwargs = service.engine.search_components.call_args.kwargs
    assert kwargs["target_product"] == IPHONE
    assert kwargs["target_project"] == PROJECT
    assert kwargs["target_build"] == BUILD
    assert all(h["product"] == IPHONE for h in response.json()["hits"])
