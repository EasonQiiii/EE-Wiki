"""Tests for query-focused rerank excerpts."""

from __future__ import annotations

from ee_wiki.retrieval.rerank_excerpt import query_focused_excerpt

_MODULE_A = "DISPLAY&SENSOR"
_NET_A0 = "IFACE_D0"
_NET_A1 = "IFACE_D1"


def test_query_focused_excerpt_centers_on_query_term() -> None:
    content = "A" * 200 + f" {_MODULE_A} {_NET_A0} {_NET_A1} " + "B" * 200
    excerpt = query_focused_excerpt(content, f"display sensor {_NET_A0}", max_len=120)
    assert _NET_A0 in excerpt
    assert len(excerpt) <= 120


def test_query_focused_excerpt_returns_short_content_unchanged() -> None:
    content = f"{_MODULE_A} {_NET_A0}"
    assert query_focused_excerpt(content, "module_x", max_len=512) == content
