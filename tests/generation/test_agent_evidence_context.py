"""Tests for ADR 0012 agent evidence merging into RAG context."""

from __future__ import annotations

from ee_wiki.generation.context import merge_agent_evidence_into_context


def test_merge_evidence_with_chunks() -> None:
    out = merge_agent_evidence_into_context("[1] chunk", "## Agent evidence\nhit")
    assert out.startswith("## Agent tool evidence")
    assert "Retrieved context" in out
    assert "[1] chunk" in out


def test_merge_evidence_only() -> None:
    out = merge_agent_evidence_into_context("", "tool hit")
    assert out == "## Agent tool evidence\ntool hit"


def test_merge_skips_empty_evidence() -> None:
    assert merge_agent_evidence_into_context("[1] x", "  ") == "[1] x"
