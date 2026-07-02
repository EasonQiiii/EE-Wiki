"""Tests for LLM checkpoint format detection."""

from __future__ import annotations

import json

from ee_wiki.generation.llm.format import is_mlx_quantized_checkpoint


def test_is_mlx_quantized_checkpoint_detects_mlx_bits(tmp_path) -> None:
    model_dir = tmp_path / "mlx-model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps({"quantization_config": {"bits": 4, "group_size": 64}}),
        encoding="utf-8",
    )
    assert is_mlx_quantized_checkpoint(model_dir) is True


def test_is_mlx_quantized_checkpoint_rejects_hf_quant_method(tmp_path) -> None:
    model_dir = tmp_path / "hf-model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        json.dumps({"quantization_config": {"quant_method": "gptq", "bits": 4}}),
        encoding="utf-8",
    )
    assert is_mlx_quantized_checkpoint(model_dir) is False
