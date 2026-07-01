"""Tests for hardware tokenization."""

import pytest


def test_tokenize_hw_text_fallback_requires_jieba() -> None:
    pytest.importorskip("jieba")
    from ee_wiki.retrieval.tokenizer import tokenize_hw_text

    tokens = tokenize_hw_text("U101 NET_VBAT 电源")
    assert "U101" in tokens
    assert any("NET" in token or "VBAT" in token for token in tokens)
