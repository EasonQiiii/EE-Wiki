"""Tests for ModelsConfig LLM path resolution."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.types import ModelsConfig


def test_resolve_llm_model_by_backend() -> None:
    mlx_path = Path("/models/mlx")
    transformers_path = Path("/models/transformers")
    models = ModelsConfig(
        base_dir=Path("/models"),
        llm_mlx_model=mlx_path,
        llm_transformers_model=transformers_path,
    )
    assert models.resolve_llm_model("mlx") == mlx_path
    assert models.resolve_llm_model("transformers") == transformers_path


def test_llm_config_key_names() -> None:
    assert ModelsConfig.llm_config_key("mlx") == "llm_mlx_model"
    assert ModelsConfig.llm_config_key("transformers") == "llm_transformers_model"
