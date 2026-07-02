"""Tests for prompt size estimation."""

from __future__ import annotations

from ee_wiki.generation.prompt_stats import estimate_llm_tokens, prompt_size_fields


def test_estimate_llm_tokens_empty() -> None:
    assert estimate_llm_tokens("") == 0


def test_estimate_llm_tokens_mixed_script() -> None:
    text = "RMII 接口说明：U101 连接 NET_MDIO。"
    assert estimate_llm_tokens(text) > 0
    fields = prompt_size_fields(text)
    assert fields["prompt_chars"] == len(text)
    assert fields["prompt_tokens_est"] == estimate_llm_tokens(text)
