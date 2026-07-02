"""Tests for query expansion and boost behavior."""

from __future__ import annotations

from ee_wiki.retrieval.query_boost import query_boost_tokens
from ee_wiki.retrieval.query_expand import expand_hw_query

_PIN_QUERY = "proj_a build_b 的 module_x pin 有哪几组信号"


def test_expand_hw_query_is_noop() -> None:
    assert expand_hw_query(_PIN_QUERY) == _PIN_QUERY


def test_query_boost_tokens_use_query_terms_only() -> None:
    tokens = query_boost_tokens(_PIN_QUERY)
    lowered = {token.casefold() for token in tokens}
    assert "module" in lowered
    assert "proj" in lowered
    assert "pin" not in lowered
    assert "IFACE" not in lowered
    assert "MEM" not in lowered
