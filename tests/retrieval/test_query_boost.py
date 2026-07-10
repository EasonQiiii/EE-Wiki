"""Tests for query keyword boost tokens."""

from __future__ import annotations

from ee_wiki.retrieval.query_boost import query_boost_tokens


def test_lcd_pin_query_adds_interface_nets() -> None:
    tokens = query_boost_tokens("lcd的pin有哪些")
    assert "lcd" in tokens
    assert "T_CS" in tokens
    assert "T_MOSI" in tokens
