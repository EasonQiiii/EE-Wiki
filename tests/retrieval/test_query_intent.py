"""Tests for retrieval query intent hints."""

from __future__ import annotations

from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.retrieval.query_intent import effective_document_type, prefers_schematic_sources

_PIN_QUERY = "proj_a build_b 的 module_x pin 有哪几组信号"


def test_prefers_schematic_sources_for_pin_queries() -> None:
    assert prefers_schematic_sources(_PIN_QUERY)


def test_prefers_schematic_sources_false_for_general_notes() -> None:
    assert not prefers_schematic_sources("设备重启进 recovery 怎么设置")


def test_effective_document_type_defaults_to_schematic_for_pin_queries() -> None:
    assert effective_document_type(_PIN_QUERY, None) == SCHEMATIC_DOCUMENT_TYPE


def test_effective_document_type_respects_explicit_filter() -> None:
    assert effective_document_type("module pin", "engineering_note") == "engineering_note"
