"""Tests for LLM backend factory."""

from __future__ import annotations

from pathlib import Path

import pytest

from ee_wiki.common.config import (
    ApiConfig,
    AppConfig,
    ChunkingConfig,
    ExcelConfig,
    GenerationConfig,
    IndexingConfig,
    ProsePdfConfig,
    RetrievalConfig,
    SchematicPdfConfig,
    WordConfig,
)
from ee_wiki.common.errors import ConfigError
from ee_wiki.common.types import DataLayoutConfig, ModelsConfig
from ee_wiki.generation.llm.errors import LlmLoadError
from ee_wiki.generation.llm.factory import build_llm_backend
from ee_wiki.generation.llm.local import LocalLlmBackend
from ee_wiki.generation.llm.mlx import MlxLlmBackend


def _app_config(
    *,
    llm_backend: str,
    llm_mlx_model: Path | None = None,
    llm_transformers_model: Path | None = None,
) -> AppConfig:
    return AppConfig(
        repo_root=Path("/repo"),
        raw_dir=Path("/repo/data/raw"),
        processed_dir=Path("/repo/data/processed"),
        indexes_dir=Path("/repo/data/indexes"),
        graph_dir=Path("/repo/data/graph"),
        models=ModelsConfig(
            base_dir=Path("/repo/models"),
            llm_mlx_model=llm_mlx_model,
            llm_transformers_model=llm_transformers_model,
        ),
        schematic_pdf=SchematicPdfConfig(),
        prose_pdf=ProsePdfConfig(),
        excel=ExcelConfig(),
        word=WordConfig(),
        chunking=ChunkingConfig(),
        indexing=IndexingConfig(),
        retrieval=RetrievalConfig(
            top_k_embed=20,
            top_k_bm25=20,
            top_k_final=8,
            scope_inheritance=True,
            top_k_dense=4,
            top_k_sparse=4,
        ),
        data_layout=DataLayoutConfig(
            enterprise_project="global",
            project_shared_build="common",
            document_type_folders={"note": "engineering_note"},
            raw_dir=Path("/repo/data/raw"),
            processed_dir=Path("/repo/data/processed"),
        ),
        generation=GenerationConfig(llm_backend=llm_backend, max_new_tokens=512),
        api=ApiConfig(host="0.0.0.0", port=8080),
    )


def test_build_llm_backend_selects_mlx(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    config = _app_config(llm_backend="mlx", llm_mlx_model=model_dir)

    backend = build_llm_backend(config)

    assert isinstance(backend, MlxLlmBackend)


def test_build_llm_backend_selects_transformers(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    config = _app_config(llm_backend="transformers", llm_transformers_model=model_dir)

    backend = build_llm_backend(config)

    assert isinstance(backend, LocalLlmBackend)


def test_build_llm_backend_rejects_mlx_weights_for_transformers(tmp_path: Path) -> None:
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text(
        '{"quantization_config": {"bits": 4, "group_size": 64}}',
        encoding="utf-8",
    )
    config = _app_config(llm_backend="transformers", llm_transformers_model=model_dir)

    with pytest.raises(LlmLoadError, match="MLX-quantized checkpoint"):
        build_llm_backend(config)


def test_build_llm_backend_rejects_unknown_backend(tmp_path: Path) -> None:
    config = _app_config(llm_backend="ollama", llm_mlx_model=tmp_path)

    with pytest.raises(ConfigError, match="Unsupported generation.llm_backend"):
        build_llm_backend(config)


def test_build_llm_backend_requires_backend_specific_model(tmp_path: Path) -> None:
    config = _app_config(llm_backend="mlx", llm_transformers_model=tmp_path)

    with pytest.raises(RuntimeError, match="models.llm_mlx_model is not configured"):
        build_llm_backend(config)
