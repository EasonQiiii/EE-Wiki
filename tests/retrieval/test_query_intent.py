"""Tests for retrieval query intent hints."""

from __future__ import annotations

from ee_wiki.retrieval.query_intent import prefers_schematic_sources


def test_prefers_schematic_sources_for_pin_queries() -> None:
    assert prefers_schematic_sources("logan p1的oled pin有哪几组信号")


def test_prefers_schematic_sources_false_for_general_notes() -> None:
    assert not prefers_schematic_sources("iPad 重启进 recovery 怎么设置")
