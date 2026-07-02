"""Tests for query expansion and boost behavior."""

from __future__ import annotations

from ee_wiki.retrieval.query_boost import query_boost_tokens
from ee_wiki.retrieval.query_expand import expand_hw_query


def test_expand_hw_query_is_noop() -> None:
    query = "logan p1的oled pin有哪几组信号"
    assert expand_hw_query(query) == query


def test_query_boost_tokens_use_query_terms_only() -> None:
    tokens = query_boost_tokens("logan p1的oled pin有哪几组信号")
    assert "oled" in {token.casefold() for token in tokens}
    assert "DCMI" not in tokens
    assert "FSMC" not in tokens
