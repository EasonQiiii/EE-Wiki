"""Configuration loading for EE-Wiki."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ee_wiki.common.errors import ConfigError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig, ModelsConfig

logger = get_logger(__name__)


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repository root by walking up for ``pyproject.toml``.

    Args:
        start: Directory to begin the search from. Defaults to the current directory.

    Returns:
        Absolute path to the repository root.

    Raises:
        ConfigError: If no ``pyproject.toml`` is found.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise ConfigError(f"Could not find pyproject.toml from {current}")


@dataclass(frozen=True)
class SchematicPdfConfig:
    """Settings for schematic PDF vision parsing."""

    dpi: int = 200
    max_pages: int | None = None
    layout_zoom: float = 2.0
    min_figure_area: int = 10_000
    ocr_text_max_chars: int = 2500
    max_new_tokens: int = 1536
    temperature: float = 0.1
    do_sample: bool = False
    images_rel_prefix: str = "images"
    fidelity_mode: str = "vlm_plus_ocr"
    vlm_max_image_side: int = 1280


@dataclass(frozen=True)
class ChunkingConfig:
    """Document chunking parameters for indexing."""

    max_chars: int = 1500
    overlap_chars: int = 100
    min_chars: int = 50
    excerpt_chars: int = 200


@dataclass(frozen=True)
class RetrievalConfig:
    """Hybrid retrieval hyperparameters."""

    top_k_embed: int
    top_k_bm25: int
    top_k_final: int
    scope_inheritance: bool
    top_k_dense: int
    top_k_sparse: int
    expand_sections: bool = True


@dataclass(frozen=True)
class GenerationConfig:
    """Answer generation settings."""

    llm_backend: str = "mlx"
    max_new_tokens: int = 1024


@dataclass(frozen=True)
class ApiConcurrencyConfig:
    """Concurrency limits for LAN-facing RAG endpoints."""

    max_concurrent: int = 1
    max_queue_depth: int = 8
    retry_after_seconds: int = 15


@dataclass(frozen=True)
class ApiConfig:
    """HTTP server settings."""

    host: str
    port: int
    warmup_on_startup: bool = False
    concurrency: ApiConcurrencyConfig = field(default_factory=ApiConcurrencyConfig)


@dataclass(frozen=True)
class AppConfig:
    """Loaded application configuration."""

    repo_root: Path
    raw_dir: Path
    processed_dir: Path
    indexes_dir: Path
    graph_dir: Path
    models: ModelsConfig
    schematic_pdf: SchematicPdfConfig
    chunking: ChunkingConfig
    retrieval: RetrievalConfig
    data_layout: DataLayoutConfig
    generation: GenerationConfig
    api: ApiConfig

    @property
    def models_dir(self) -> Path:
        return self.models.base_dir


def _resolve_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (repo_root / path).resolve()


def _models_base_dir(repo_root: Path, models: dict) -> Path:
    override = os.environ.get("EE_WIKI_MODELS_DIR")
    if override:
        path = Path(override)
        return path if path.is_absolute() else (repo_root / path).resolve()
    return _resolve_path(repo_root, models.get("base_dir", "models"))


def _data_root(repo_root: Path) -> Path:
    """Return the ``data/`` directory, honoring ``EE_WIKI_DATA_DIR`` when set."""
    override = os.environ.get("EE_WIKI_DATA_DIR")
    if override:
        path = Path(override)
        return path if path.is_absolute() else (repo_root / path).resolve()
    return (repo_root / "data").resolve()


def _load_models_config(repo_root: Path, models: dict) -> ModelsConfig:
    base_dir = _models_base_dir(repo_root, models)
    resolver = ModelsConfig(base_dir=base_dir)
    legacy_llm = models.get("llm_model")
    mlx_name = models.get("llm_mlx_model") or legacy_llm
    transformers_name = models.get("llm_transformers_model")
    cfg = ModelsConfig(
        base_dir=base_dir,
        layout_model=resolver.resolve(models.get("layout_model")),
        visual_model=resolver.resolve(models.get("visual_model")),
        embedding_model=resolver.resolve(models.get("embedding_model")),
        reranker_model=resolver.resolve(models.get("reranker_model")),
        llm_transformers_model=resolver.resolve(transformers_name),
        llm_mlx_model=resolver.resolve(mlx_name),
    )
    return cfg


def load_config(
    config_path: Path | None = None,
    repo_root: Path | None = None,
) -> AppConfig:
    """Load YAML configuration and apply environment overrides.

    Args:
        config_path: Optional explicit path to ``default.yaml``.
        repo_root: Optional repository root. Inferred when omitted.

    Returns:
        Parsed :class:`AppConfig`.

    Raises:
        ConfigError: If the config file is missing or malformed.
    """
    root = repo_root or find_repo_root()
    path = config_path or (root / "config" / "default.yaml")
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Configuration root must be a mapping: {path}")

    data = raw.get("data", {})
    retrieval = raw.get("retrieval", {})
    ingestion = raw.get("ingestion", {})
    data_layout = raw.get("data_layout", {})
    chunking = raw.get("chunking", {})
    models = raw.get("models", {})
    schematic = ingestion.get("schematic_pdf", {})
    api = raw.get("api", {})
    concurrency = api.get("concurrency", {})
    generation = raw.get("generation", {})

    document_type_folders = data_layout.get("document_type_folders", {})
    if not isinstance(document_type_folders, dict) or not document_type_folders:
        raise ConfigError("data_layout.document_type_folders must be a non-empty mapping")

    data_parent = _data_root(root)
    raw_dir = data_parent / Path(data.get("raw_dir", "data/raw")).name
    processed_dir = data_parent / Path(data.get("processed_dir", "data/processed")).name
    indexes_dir = data_parent / Path(data.get("indexes_dir", "data/indexes")).name
    graph_dir = data_parent / Path(data.get("graph_dir", "data/graph")).name

    layout = DataLayoutConfig(
        enterprise_project=str(data_layout.get("enterprise_project", "global")),
        project_shared_build=str(data_layout.get("project_shared_build", "common")),
        document_type_folders={str(k): str(v) for k, v in document_type_folders.items()},
        raw_dir=raw_dir,
        processed_dir=processed_dir,
    )

    config = AppConfig(
        repo_root=root,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        indexes_dir=indexes_dir,
        graph_dir=graph_dir,
        models=_load_models_config(root, models),
        schematic_pdf=SchematicPdfConfig(
            dpi=int(schematic.get("dpi", 200)),
            max_pages=schematic.get("max_pages"),
            layout_zoom=float(schematic.get("layout_zoom", 2.0)),
            min_figure_area=int(schematic.get("min_figure_area", 10_000)),
            ocr_text_max_chars=int(schematic.get("ocr_text_max_chars", 2500)),
            max_new_tokens=int(schematic.get("max_new_tokens", 1536)),
            temperature=float(schematic.get("temperature", 0.1)),
            do_sample=bool(schematic.get("do_sample", False)),
            images_rel_prefix=str(schematic.get("images_rel_prefix", "images")),
            fidelity_mode=str(schematic.get("fidelity_mode", "vlm_plus_ocr")),
            vlm_max_image_side=int(schematic.get("vlm_max_image_side", 1280)),
        ),
        chunking=ChunkingConfig(
            max_chars=int(chunking.get("max_chars", 1500)),
            overlap_chars=int(chunking.get("overlap_chars", 100)),
            min_chars=int(chunking.get("min_chars", 50)),
            excerpt_chars=int(chunking.get("excerpt_chars", 200)),
        ),
        retrieval=RetrievalConfig(
            top_k_embed=int(retrieval.get("top_k_embed", 20)),
            top_k_bm25=int(retrieval.get("top_k_bm25", 20)),
            top_k_final=int(retrieval.get("top_k_final", 8)),
            scope_inheritance=bool(retrieval.get("scope_inheritance", True)),
            top_k_dense=int(retrieval.get("top_k_dense", 4)),
            top_k_sparse=int(retrieval.get("top_k_sparse", 4)),
            expand_sections=bool(retrieval.get("expand_sections", True)),
        ),
        data_layout=layout,
        generation=GenerationConfig(
            llm_backend=str(generation.get("llm_backend", "mlx")),
            max_new_tokens=int(generation.get("max_new_tokens", 1024)),
        ),
        api=ApiConfig(
            host=str(api.get("host", "0.0.0.0")),
            port=int(api.get("port", 8080)),
            warmup_on_startup=bool(api.get("warmup_on_startup", False)),
            concurrency=ApiConcurrencyConfig(
                max_concurrent=int(concurrency.get("max_concurrent", 1)),
                max_queue_depth=int(concurrency.get("max_queue_depth", 8)),
                retry_after_seconds=int(concurrency.get("retry_after_seconds", 15)),
            ),
        ),
    )
    logger.debug("Loaded config from %s (raw_dir=%s)", path, config.raw_dir)
    return config


