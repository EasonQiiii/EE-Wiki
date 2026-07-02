"""Tests for local LLM prompt formatting and model detection."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ee_wiki.generation.llm.local import LlmLoadError, _format_causal_prompt, detect_model_kind


def test_format_causal_prompt_uses_chat_template_when_available() -> None:
    tokenizer = MagicMock()
    tokenizer.chat_template = "<template>"
    tokenizer.apply_chat_template.return_value = "<formatted>"

    result = _format_causal_prompt(tokenizer, "Hello")

    assert result == "<formatted>"
    tokenizer.apply_chat_template.assert_called_once()


def test_format_causal_prompt_falls_back_without_chat_template() -> None:
    tokenizer = MagicMock()
    tokenizer.chat_template = None

    result = _format_causal_prompt(tokenizer, "Hello")

    assert result == "Hello"
    tokenizer.apply_chat_template.assert_not_called()


def test_detect_model_kind_qwen3_vl(tmp_path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps({"model_type": "qwen3_vl", "architectures": ["Qwen3VLForConditionalGeneration"]}),
        encoding="utf-8",
    )
    assert detect_model_kind(tmp_path) == "qwen3_vl"


def test_detect_model_kind_rejects_nvfp4(tmp_path) -> None:
    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "model_type": "qwen3_5",
                "architectures": ["Qwen3_5ForConditionalGeneration"],
                "quantization_config": {"config_groups": {"group_0": {}}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LlmLoadError, match="NVFP4"):
        detect_model_kind(tmp_path)
