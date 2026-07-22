"""Golden acceptance regressions — utterances that already burned production UX.

These tests are the contract. If they fail, do not argue with Open WebUI screenshots:
fix the pipeline until this file is green.

Covered failure modes (2026-07):
1. OWUI sends no body scope → question ``logan p1`` must still resolve.
2. ``完整trace`` / ``原理图DP_…`` must hit connectivity authority, not FA unbound,
   not hybrid RAG prose that invents 起点→终点 paths.
3. Advisory-only / missing sidecar → explicit refusal, never a guessed net path.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

from ee_wiki.agents.fa_mode import is_wiki_connectivity_query, resolve_chat_mode
from ee_wiki.api.routes.chat import _fetch_stream_result
from ee_wiki.connectivity.intent import detect_trace_intent
from ee_wiki.generation.service import AnswerStreamResult
from ee_wiki.retrieval.scope_from_question import merge_scope_from_question

# Exact user utterance that produced invented C2833→U9750→C2835 prose.
_GOLDEN_TRACE = "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace"

# Narrative path prose from the failed hybrid-RAG answer (not pin-table text).
_FABRICATION_MARKERS = (
    "起点：",
    "终点：",
    "中间节点",
    "完整网络追踪如下",
    "电气连接路径",
    "页面 74",
    "Thunderbolt",
)


def _chunks(text: str) -> AnswerStreamResult:
    return AnswerStreamResult(citations=[], text_chunks=iter([text]))


def _service(app_config, *, llm_modes: list[str] | None = None) -> MagicMock:
    """Minimal RagService double with FA classify ready to mis-route to fa."""
    service = MagicMock()
    # Ensure connectivity gate is on (shipped default, but do not rely on silence).
    conn = replace(
        app_config.schematic_pdf.connectivity,
        enabled=True,
        require_authority_for_trace=True,
    )
    schematic = replace(app_config.schematic_pdf, connectivity=conn)
    service.config = replace(app_config, schematic_pdf=schematic)
    service.engine = MagicMock()
    service.engine.get_scope_catalog.return_value = None
    service.llm = MagicMock()
    service.llm.generate_stream = None
    # If the gate regresses, classify would push FA — tests must still pass.
    service.llm.generate.side_effect = llm_modes or [
        "MODE: fa",
        "TASK: wiki\nROLES: none",
    ]
    service.stream_answer.return_value = _chunks("SHOULD_NOT_REACH_RAG")
    return service


def test_golden_trace_intent_and_mode_contracts(repo_root, app_config) -> None:
    """Layer-0: intent + mode must classify the golden utterance correctly."""
    intent = detect_trace_intent(_GOLDEN_TRACE)
    assert intent is not None, "完整trace / 原理图DP_ must be a trace intent"
    assert intent.kind == "net"
    assert intent.query == "DP_TBTSNK1_ML_C_N<1>"

    assert is_wiki_connectivity_query(_GOLDEN_TRACE)
    mode = resolve_chat_mode(
        _GOLDEN_TRACE,
        history=None,
        llm=MagicMock(generate=MagicMock(return_value="MODE: fa")),
        config=app_config,
    )
    assert mode == "wiki"

    product, project, build = merge_scope_from_question(
        _GOLDEN_TRACE, config=app_config, engine=None
    )
    assert (product, project, build) == ("ipad", "logan", "p1")


def test_golden_trace_missing_sidecar_refuses_no_rag(app_config) -> None:
    """No *.connectivity.json → refusal markdown; never FA / never RAG invent."""
    service = _service(app_config)
    result = _fetch_stream_result(
        service,
        _GOLDEN_TRACE,
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
        connectivity_query=None,
    )
    content = "".join(result.text_chunks)
    assert "权威" in content or "无法追踪" in content
    assert "FA session" not in content
    assert "FA check-in" not in content
    assert "SHOULD_NOT_REACH_RAG" not in content
    for marker in _FABRICATION_MARKERS:
        assert marker not in content, f"fabricated connectivity marker: {marker}"
    service.stream_answer.assert_not_called()


def test_golden_trace_advisory_only_refuses(app_config) -> None:
    """pdf_geometry / OCR-only → authoritative refusal, not a pin story."""
    service = _service(app_config)
    cq = MagicMock()
    cq.resolve_trace.return_value = {
        "query": "DP_TBTSNK1_ML_C_N",
        "kind": "trace_net",
        "found": False,
        "authority": "insufficient",
        "pins": [],
        "pin_count": 0,
        "advisory_pins": [
            {
                "refdes": "U9750",
                "pin": "4",
                "net": "DP_TBTSNK1_ML_C_N",
                "evidence": "pdf_geometry",
            }
        ],
        "note": "advisory only",
    }
    result = _fetch_stream_result(
        service,
        _GOLDEN_TRACE,
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
        connectivity_query=cq,
    )
    content = "".join(result.text_chunks)
    assert "authoritative-only" in content or "权威" in content
    assert "C2833" not in content
    assert "起点：" not in content
    service.stream_answer.assert_not_called()
    # A/B: chat TurnScope lock feeds connectivity (and would feed ToolBus).
    kwargs = cq.resolve_trace.call_args.kwargs
    assert kwargs.get("project") == "logan"
    assert kwargs.get("build") == "p1"
    assert kwargs.get("product") == "ipad"


def test_turn_scope_locked_once_fa_session_does_not_reinfer(app_config) -> None:
    """D: ensure_fa_session must not invent scope when chat omitted the lock."""
    from ee_wiki.agents.fa_session import ensure_fa_session

    session = ensure_fa_session(
        _GOLDEN_TRACE,
        history=None,
        product=None,
        project=None,
        build=None,
        config=app_config,
        ctx=None,
    )
    assert session.product is None
    assert session.project is None
    assert session.build is None


def test_golden_trace_cad_netlist_returns_table_not_path(app_config) -> None:
    """Authoritative cad_netlist → pin table only; no 起点→终点 narrative."""
    service = _service(app_config)
    cq = MagicMock()
    cq.resolve_trace.return_value = {
        "query": "DP_TBTSNK1_ML_C_N",
        "kind": "trace_net",
        "found": True,
        "authority": "authoritative",
        "authoritative": True,
        "resolved_net": "DP_TBTSNK1_ML_C_N",
        "pins": [
            {
                "refdes": "C2833",
                "pin": "1",
                "net": "DP_TBTSNK1_ML_C_N",
                "evidence": "cad_netlist",
            },
            {
                "refdes": "U9750",
                "pin": "4",
                "net": "DP_TBTSNK1_ML_C_N",
                "evidence": "cad_netlist",
            },
            {
                "refdes": "C2835",
                "pin": "1",
                "net": "DP_TBTSNK1_ML_C_N",
                "evidence": "cad_netlist",
            },
        ],
        "pin_count": 3,
        "documents": [{"source_file": "logan_p1.net"}],
        "limitations": "",
    }
    result = _fetch_stream_result(
        service,
        _GOLDEN_TRACE,
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
        connectivity_query=cq,
    )
    content = "".join(result.text_chunks)
    assert "| refdes | pin | net | evidence |" in content
    assert "pin list" in content.lower() or "board-verified" in content
    for marker in _FABRICATION_MARKERS:
        assert marker not in content, f"fabricated connectivity marker: {marker}"
    assert "C2833" in content and "U9750" in content and "C2835" in content
    service.stream_answer.assert_not_called()


def test_golden_trace_boardview_refused(app_config) -> None:
    """BoardView (.brd) is advisory reference only — a boardview-only trace
    must be refused (no pin table), never presented as verified trace."""
    service = _service(app_config)
    cq = MagicMock()
    cq.resolve_trace.return_value = {
        "query": "DP_TBTSNK1_ML_C_N",
        "kind": "trace_net",
        "found": True,
        "authority": "insufficient",
        "authoritative": False,
        "pins": [],
        "pin_count": 0,
        "advisory_pins": [
            {
                "refdes": "C2833",
                "pin": "1",
                "net": "DP_TBTSNK1_ML_C_N",
                "evidence": "boardview",
            },
            {
                "refdes": "U9750",
                "pin": "4",
                "net": "DP_TBTSNK1_ML_C_N",
                "evidence": "boardview",
            },
            {
                "refdes": "C2835",
                "pin": "1",
                "net": "DP_TBTSNK1_ML_C_N",
                "evidence": "boardview",
            },
        ],
        "documents": [{"source_file": "logan_p1.brd"}],
        "limitations": "",
    }
    result = _fetch_stream_result(
        service,
        _GOLDEN_TRACE,
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
        connectivity_query=cq,
    )
    content = "".join(result.text_chunks)
    # Refusal, not a pin table.
    assert "无法提供可靠的连接追踪" in content or "authoritative-only" in content
    assert "| refdes | pin | net | evidence |" not in content
    for marker in _FABRICATION_MARKERS:
        assert marker not in content, f"fabricated connectivity marker: {marker}"
    service.stream_answer.assert_not_called()


def test_golden_trace_bus_index_exact_not_whole_bus(app_config) -> None:
    """Ask ``…<1>`` → only ``<1>`` pins; never ``<0>``/``<2>`` bleed or ``<0>`` header."""
    service = _service(app_config)
    cq = MagicMock()
    cq.resolve_trace.return_value = {
        "query": "DP_TBTSNK1_ML_C_N<1>",
        "kind": "trace_net",
        "found": True,
        "authority": "authoritative",
        "authoritative": True,
        "match": "exact",
        "resolved_net": "DP_TBTSNK1_ML_C_N<1>",
        "pins": [
            {
                "refdes": "C2833",
                "pin": "1",
                "net": "DP_TBTSNK1_ML_C_N<1>",
                "evidence": "boardview",
            },
            {
                "refdes": "U9750",
                "pin": "4",
                "net": "DP_TBTSNK1_ML_C_N<1>",
                "evidence": "boardview",
            },
        ],
        "pin_count": 2,
        "documents": [],
        "limitations": "",
    }
    result = _fetch_stream_result(
        service,
        _GOLDEN_TRACE,
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
        connectivity_query=cq,
    )
    content = "".join(result.text_chunks)
    assert "DP_TBTSNK1_ML_C_N<1>" in content
    assert "DP_TBTSNK1_ML_C_N<0>" not in content
    assert "DP_TBTSNK1_ML_C_N<2>" not in content
    args = cq.resolve_trace.call_args
    # kind, query positional
    assert args.args[1] == "DP_TBTSNK1_ML_C_N<1>"
    service.stream_answer.assert_not_called()


def test_golden_trace_missing_bus_index_member_refuses(app_config) -> None:
    service = _service(app_config)
    cq = MagicMock()
    cq.resolve_trace.return_value = {
        "query": "DP_TBTSNK1_ML_C_N<1>",
        "kind": "trace_net",
        "found": False,
        "authority": "not_found",
        "error": (
            "No exact net `DP_TBTSNK1_ML_C_N<1>`. "
            "Related bus members: `DP_TBTSNK1_ML_C_N<0>`."
        ),
        "candidates": ["DP_TBTSNK1_ML_C_N<0>"],
        "pins": [],
        "pin_count": 0,
    }
    result = _fetch_stream_result(
        service,
        _GOLDEN_TRACE,
        bypass_rag=False,
        target_product=None,
        target_project=None,
        target_build=None,
        document_type=None,
        top_k=None,
        cancel_event=None,
        task=None,
        history=None,
        connectivity_query=cq,
    )
    content = "".join(result.text_chunks)
    assert "无法提供可靠的连接追踪" in content or "权威" in content
    assert "C2831" not in content
    assert "起点：" not in content
