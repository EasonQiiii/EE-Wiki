"""Tests for retrieval document-type filter helpers."""

from __future__ import annotations

from ee_wiki.retrieval.query_intent import effective_document_type


def test_effective_document_type_passes_explicit_filter() -> None:
    assert effective_document_type("any query", "engineering_note") == "engineering_note"
    assert effective_document_type("RMII pin", "schematic") == "schematic"


def test_effective_document_type_does_not_infer_from_query() -> None:
    assert effective_document_type("module_x pin 有哪几组信号", None) is None
    assert effective_document_type("nRF24L01+有哪些Pin", None) is None
