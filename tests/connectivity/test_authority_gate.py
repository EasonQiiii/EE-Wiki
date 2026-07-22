"""Tests for the authoritative-only trace gate (ADR 0009 / 0010)."""

from __future__ import annotations

from ee_wiki.connectivity.authority import (
    AuthorityPolicy,
    annotate_module_nets,
    apply_authority_gate,
)
from ee_wiki.connectivity.chat import answer_trace_question
from ee_wiki.connectivity.intent import detect_trace_intent


def _net_result(evidence: str) -> dict:
    return {
        "query": "EDP_AUXP",
        "kind": "trace_net",
        "found": True,
        "pins": [{"refdes": "U1", "pin": "A12", "net": "EDP_AUXP", "evidence": evidence}],
        "pin_count": 1,
        "documents": [],
        "limitations": "x",
    }


def test_cad_netlist_is_authoritative() -> None:
    gated = apply_authority_gate(_net_result("cad_netlist"), AuthorityPolicy())
    assert gated["authoritative"] is True
    assert gated["authority"] == "authoritative"
    assert gated["found"] is True
    assert len(gated["pins"]) == 1


def test_boardview_is_advisory_not_authoritative() -> None:
    """BoardView (.brd) is advisory reference only — a trace with only
    boardview evidence must be refused, not returned as verified."""
    gated = apply_authority_gate(_net_result("boardview"), AuthorityPolicy())
    assert gated["authoritative"] is False
    assert gated["authority"] == "insufficient"
    assert gated["found"] is False
    assert gated["pins"] == []
    assert gated["advisory_pins"][0]["evidence"] == "boardview"
    assert gated["note"]


def test_advisory_only_is_refused() -> None:
    gated = apply_authority_gate(_net_result("pdf_geometry"), AuthorityPolicy())
    assert gated["authoritative"] is False
    assert gated["authority"] == "insufficient"
    assert gated["found"] is False
    assert gated["pins"] == []
    assert gated["advisory_pins"][0]["evidence"] == "pdf_geometry"
    assert gated["note"]


def test_not_found_is_not_a_refusal() -> None:
    empty = {"query": "X", "kind": "trace_net", "found": False, "pins": [], "pin_count": 0}
    gated = apply_authority_gate(empty, AuthorityPolicy())
    assert gated["authority"] == "not_found"
    assert gated["found"] is False


def test_policy_disabled_keeps_advisory() -> None:
    policy = AuthorityPolicy(require_authority=False)
    gated = apply_authority_gate(_net_result("ocr_spatial"), policy)
    assert gated["authoritative"] is False
    assert gated["authority"] == "advisory"
    assert gated["found"] is True  # not refused when the gate is off


def test_module_nets_always_advisory() -> None:
    result = {"query": "DISPLAY", "kind": "module_nets", "found": True, "modules": [{"x": 1}]}
    annotated = annotate_module_nets(result, AuthorityPolicy())
    assert annotated["authoritative"] is False
    assert annotated["authority"] == "advisory"


def test_mixed_evidence_keeps_only_authoritative() -> None:
    result = {
        "query": "J1",
        "kind": "connector_pins",
        "found": True,
        "pins": [
            {"refdes": "J1", "pin": "1", "net": "N1", "evidence": "cad_netlist"},
            {"refdes": "J1", "pin": "2", "net": "N2", "evidence": "ocr_spatial"},
        ],
        "connectors": [{"refdes": "J1", "evidence": "pdf_geometry"}],
    }
    gated = apply_authority_gate(result, AuthorityPolicy())
    assert gated["authority"] == "authoritative"
    assert [p["pin"] for p in gated["pins"]] == ["1"]
    assert gated["advisory_pins"][0]["pin"] == "2"
    assert gated["advisory_connectors"]


def test_detect_trace_intent_net() -> None:
    intent = detect_trace_intent("trace net EDP_AUXP please")
    assert intent is not None
    assert intent.kind == "net"
    assert intent.query == "EDP_AUXP"


def test_detect_trace_intent_chinese_full_trace() -> None:
    """``完整trace`` must match — ``\\btrace\\b`` fails after Chinese chars."""
    intent = detect_trace_intent(
        "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace"
    )
    assert intent is not None
    assert intent.kind == "net"
    assert intent.query == "DP_TBTSNK1_ML_C_N<1>"


def test_detect_trace_intent_pins() -> None:
    intent = detect_trace_intent("U502 的 FB 引脚连接到哪个网络？")
    assert intent is not None
    assert intent.kind == "pins"
    assert intent.query == "U502"


def test_detect_trace_intent_ignores_plain_recall() -> None:
    # Asking for a part number / net name is a recall question, not a trace.
    assert detect_trace_intent("以太网 PHY 芯片型号是什么？") is None
    assert detect_trace_intent("What is the ethernet PHY part number?") is None


def test_chat_refuses_without_sidecar() -> None:
    reply = answer_trace_question(
        "trace net EDP_AUXP",
        cq=None,
        connectivity_enabled=True,
        project="logan",
        build="p1",
    )
    assert reply is not None
    assert "权威连接数据" in reply


def test_chat_passthrough_for_non_trace() -> None:
    reply = answer_trace_question(
        "以太网 PHY 芯片型号是什么？",
        cq=None,
        connectivity_enabled=True,
        project="logan",
        build="p1",
    )
    assert reply is None


def test_chat_disabled_passthrough() -> None:
    reply = answer_trace_question(
        "trace net EDP_AUXP",
        cq=None,
        connectivity_enabled=False,
        project="logan",
        build="p1",
    )
    assert reply is None
