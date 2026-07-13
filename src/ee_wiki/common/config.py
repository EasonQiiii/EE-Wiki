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
class IndexingConfig:
    """Index build settings for embedding and BM25."""

    embed_device: str = "cpu"
    embed_batch_size: int = 8


@dataclass(frozen=True)
class GraphConfig:
    """Knowledge graph build/query settings (V3)."""

    scope_inheritance: bool = True
    power_tree: bool = True


@dataclass(frozen=True)
class RulesConfig:
    """Engineering rules engine settings (V3 P4)."""

    enabled: bool = True
    pack_dir: str = "config/rules"


@dataclass(frozen=True)
class ProsePdfConfig:
    """Settings for prose PDF text extraction and OCR fallback."""

    max_pages: int | None = None
    min_text_chars: int = 40
    ocr_dpi: int = 200
    ocr_language: str = "auto"
    ocr_language_fallback: str = "eng+chi_sim"
    tessdata_dir: Path | None = None
    extract_images: bool = True
    describe_images: str = "ocr"
    min_image_area: int = 10_000
    max_images_per_page: int = 5
    images_rel_prefix: str = "images"
    image_dedup_max_pages: int = 3


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
    save_page_images: bool = True


@dataclass(frozen=True)
class DatasheetPdfConfig:
    """Settings for datasheet PDF parsing via VLM page-level extraction."""

    max_pages: int | None = None
    min_text_chars_for_skip: int = 500
    vector_line_threshold: int = 50
    image_area_threshold: float = 0.6
    max_new_tokens: int = 2048
    vlm_max_image_side: int = 1280
    temperature: float = 0.1
    do_sample: bool = False
    ocr_fidelity: bool = True
    save_page_images: bool = True
    images_rel_prefix: str = "images"
    vlm_quality_gate: bool = True
    vlm_max_empty_cell_ratio: float = 0.45
    vlm_min_length_ratio: float = 0.25
    vlm_max_garble_ratio: float = 0.12
    vlm_min_ocr_chars_for_fallback: int = 80
    vlm_min_table_rows_vs_ocr_lines: float = 0.15


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
    min_rerank_score: float | None = None
    scope_cascade: bool = True
    scope_sufficient_rerank: float = -3.0
    scope_quota_build: int = 6
    scope_quota_common: int = 2
    scope_quota_global: int = 2
    case_lookup: bool = True
    case_lookup_boost: int = 3
    graph_enrichment: bool = False
    graph_enrichment_max_hops: int = 1
    graph_enrichment_max_nodes: int = 12


@dataclass(frozen=True)
class ExcelConfig:
    """Settings for Excel workbook ingest."""

    output_format: str = "markdown_table"
    max_rows_per_sheet: int | None = None
    include_empty_sheets: bool = False


@dataclass(frozen=True)
class WordConfig:
    """Settings for Word document ingest."""

    libreoffice_path: Path | None = None


@dataclass(frozen=True)
class IworkConfig:
    """Settings for Apple Keynote / Numbers ingest on macOS."""

    enabled: bool = True
    keynote_export_timeout_seconds: int = 600
    numbers_export_timeout_seconds: int = 600
    quit_apps_after_export: bool = False


@dataclass(frozen=True)
class GenerationConfig:
    """Answer generation settings."""

    llm_backend: str = "mlx"
    max_new_tokens: int = 1024
    default_task: str = "wiki"
    default_template: str = "default"
    llm_timeout_seconds: int | None = 120
    assistant_fallback: bool = True
    assistant_task: str = "assistant"
    weak_rerank_threshold: float = -2.0
    query_rewrite: bool = True
    query_rewrite_max_history_turns: int = 4
    task_classification: bool = True
    query_prepare: str = "merged"  # merged | separate — one LLM call vs rewrite + classify
    openai_base_url: str = "http://127.0.0.1:8000/v1"
    openai_model: str = ""
    openai_api_key: str | None = None
    inline_citation_images: bool = True
    max_inline_images: int = 4
    scope_inference: bool = True
    scope_inference_mode: str = "merged"  # rules | llm | merged
    show_elapsed_time: bool = False


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
    public_base_url: str | None = None
    request_timeout_seconds: int | None = 300
    max_concurrent_ingest_jobs: int = 1
    ingest_api_key: str | None = None
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
    prose_pdf: ProsePdfConfig
    schematic_pdf: SchematicPdfConfig
    datasheet_pdf: DatasheetPdfConfig
    excel: ExcelConfig
    word: WordConfig
    iwork: IworkConfig
    chunking: ChunkingConfig
    indexing: IndexingConfig
    graph: GraphConfig
    rules: RulesConfig
    retrieval: RetrievalConfig
    data_layout: DataLayoutConfig
    generation: GenerationConfig
    api: ApiConfig

    @property
    def models_dir(self) -> Path:
        return self.models.base_dir

    @property
    def rules_pack_dir(self) -> Path:
        """Absolute path to the engineering rules YAML pack."""
        return _resolve_path(self.repo_root, self.rules.pack_dir)


def _optional_positive_int(value: object) -> int | None:
    """Parse a positive integer timeout, or ``None`` when disabled."""
    if value is None:
        return None
    parsed = int(value)
    if parsed <= 0:
        return None
    return parsed


def _optional_float(value: object) -> float | None:
    """Parse a float threshold, or ``None`` when disabled."""
    if value is None:
        return None
    return float(value)


def _optional_env_secret(name: str) -> str | None:
    """Return a trimmed environment secret, or ``None`` when unset/empty.

    Args:
        name: Environment variable name.

    Returns:
        Non-empty secret string, or ``None``.
    """
    raw = os.environ.get(name)
    if raw is None:
        return None
    stripped = raw.strip()
    return stripped or None


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
    indexing = raw.get("indexing", {})
    models = raw.get("models", {})
    graph_cfg = raw.get("graph", {}) or {}
    rules_cfg = raw.get("rules", {}) or {}
    prose = ingestion.get("prose_pdf", {})
    schematic = ingestion.get("schematic_pdf", {})
    datasheet = ingestion.get("datasheet_pdf", {})
    excel = ingestion.get("excel", {})
    word = ingestion.get("word") or {}
    iwork = ingestion.get("iwork") or {}
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

    tessdata_override = os.environ.get("EE_WIKI_TESSDATA_DIR")
    tessdata_dir: Path | None = None
    if tessdata_override:
        tessdata_dir = Path(tessdata_override).expanduser()
        if not tessdata_dir.is_absolute():
            tessdata_dir = (root / tessdata_dir).resolve()
    elif prose.get("tessdata_dir"):
        tessdata_dir = _resolve_path(root, str(prose.get("tessdata_dir")))

    embed_device = os.environ.get("EE_WIKI_EMBED_DEVICE", indexing.get("embed_device", "cpu"))

    config = AppConfig(
        repo_root=root,
        raw_dir=raw_dir,
        processed_dir=processed_dir,
        indexes_dir=indexes_dir,
        graph_dir=graph_dir,
        models=_load_models_config(root, models),
        prose_pdf=ProsePdfConfig(
            max_pages=prose.get("max_pages"),
            min_text_chars=int(prose.get("min_text_chars", 40)),
            ocr_dpi=int(prose.get("ocr_dpi", 200)),
            ocr_language=str(prose.get("ocr_language", "auto")),
            ocr_language_fallback=str(prose.get("ocr_language_fallback", "eng+chi_sim")),
            tessdata_dir=tessdata_dir,
            extract_images=bool(prose.get("extract_images", True)),
            describe_images=str(prose.get("describe_images", "ocr")),
            min_image_area=int(prose.get("min_image_area", 10_000)),
            max_images_per_page=int(prose.get("max_images_per_page", 5)),
            images_rel_prefix=str(prose.get("images_rel_prefix", "images")),
            image_dedup_max_pages=int(prose.get("image_dedup_max_pages", 3)),
        ),
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
            save_page_images=bool(schematic.get("save_page_images", True)),
        ),
        datasheet_pdf=DatasheetPdfConfig(
            max_pages=datasheet.get("max_pages"),
            min_text_chars_for_skip=int(datasheet.get("min_text_chars_for_skip", 500)),
            vector_line_threshold=int(datasheet.get("vector_line_threshold", 50)),
            image_area_threshold=float(datasheet.get("image_area_threshold", 0.6)),
            max_new_tokens=int(datasheet.get("max_new_tokens", 2048)),
            vlm_max_image_side=int(datasheet.get("vlm_max_image_side", 1280)),
            temperature=float(datasheet.get("temperature", 0.1)),
            do_sample=bool(datasheet.get("do_sample", False)),
            ocr_fidelity=bool(datasheet.get("ocr_fidelity", True)),
            save_page_images=bool(datasheet.get("save_page_images", True)),
            images_rel_prefix=str(datasheet.get("images_rel_prefix", "images")),
            vlm_quality_gate=bool(datasheet.get("vlm_quality_gate", True)),
            vlm_max_empty_cell_ratio=float(
                datasheet.get("vlm_max_empty_cell_ratio", 0.45)
            ),
            vlm_min_length_ratio=float(datasheet.get("vlm_min_length_ratio", 0.25)),
            vlm_max_garble_ratio=float(datasheet.get("vlm_max_garble_ratio", 0.12)),
            vlm_min_ocr_chars_for_fallback=int(
                datasheet.get("vlm_min_ocr_chars_for_fallback", 80)
            ),
            vlm_min_table_rows_vs_ocr_lines=float(
                datasheet.get("vlm_min_table_rows_vs_ocr_lines", 0.15)
            ),
        ),
        excel=ExcelConfig(
            output_format=str(excel.get("output_format", "markdown_table")),
            max_rows_per_sheet=excel.get("max_rows_per_sheet"),
            include_empty_sheets=bool(excel.get("include_empty_sheets", False)),
        ),
        word=WordConfig(
            libreoffice_path=(
                _resolve_path(root, str(word["libreoffice_path"]))
                if word.get("libreoffice_path")
                else None
            ),
        ),
        iwork=IworkConfig(
            enabled=bool(iwork.get("enabled", True)),
            keynote_export_timeout_seconds=int(
                iwork.get("keynote_export_timeout_seconds", 600)
            ),
            numbers_export_timeout_seconds=int(
                iwork.get("numbers_export_timeout_seconds", 600)
            ),
            quit_apps_after_export=bool(iwork.get("quit_apps_after_export", False)),
        ),
        chunking=ChunkingConfig(
            max_chars=int(chunking.get("max_chars", 1500)),
            overlap_chars=int(chunking.get("overlap_chars", 100)),
            min_chars=int(chunking.get("min_chars", 50)),
            excerpt_chars=int(chunking.get("excerpt_chars", 200)),
        ),
        indexing=IndexingConfig(
            embed_device=str(embed_device),
            embed_batch_size=int(indexing.get("embed_batch_size", 8)),
        ),
        graph=GraphConfig(
            scope_inheritance=bool(
                graph_cfg.get(
                    "scope_inheritance",
                    retrieval.get("scope_inheritance", True),
                )
            ),
            power_tree=bool(graph_cfg.get("power_tree", True)),
        ),
        rules=RulesConfig(
            enabled=bool(rules_cfg.get("enabled", True)),
            pack_dir=str(rules_cfg.get("pack_dir", "config/rules")),
        ),
        retrieval=RetrievalConfig(
            top_k_embed=int(retrieval.get("top_k_embed", 20)),
            top_k_bm25=int(retrieval.get("top_k_bm25", 20)),
            top_k_final=int(retrieval.get("top_k_final", 8)),
            scope_inheritance=bool(retrieval.get("scope_inheritance", True)),
            top_k_dense=int(retrieval.get("top_k_dense", 4)),
            top_k_sparse=int(retrieval.get("top_k_sparse", 4)),
            expand_sections=bool(retrieval.get("expand_sections", True)),
            min_rerank_score=_optional_float(retrieval.get("min_rerank_score")),
            scope_cascade=bool(retrieval.get("scope_cascade", True)),
            scope_sufficient_rerank=float(retrieval.get("scope_sufficient_rerank", -3.0)),
            scope_quota_build=int(retrieval.get("scope_quota_build", 6)),
            scope_quota_common=int(retrieval.get("scope_quota_common", 2)),
            scope_quota_global=int(retrieval.get("scope_quota_global", 2)),
            case_lookup=bool(retrieval.get("case_lookup", True)),
            case_lookup_boost=int(retrieval.get("case_lookup_boost", 3)),
            graph_enrichment=bool(retrieval.get("graph_enrichment", False)),
            graph_enrichment_max_hops=int(retrieval.get("graph_enrichment_max_hops", 1)),
            graph_enrichment_max_nodes=int(
                retrieval.get("graph_enrichment_max_nodes", 12)
            ),
        ),
        data_layout=layout,
        generation=GenerationConfig(
            llm_backend=str(generation.get("llm_backend", "mlx")),
            max_new_tokens=int(generation.get("max_new_tokens", 1024)),
            default_task=str(generation.get("default_task", "wiki")),
            default_template=str(generation.get("default_template", "default")),
            llm_timeout_seconds=_optional_positive_int(generation.get("llm_timeout_seconds", 120)),
            assistant_fallback=bool(generation.get("assistant_fallback", True)),
            assistant_task=str(generation.get("assistant_task", "assistant")),
            weak_rerank_threshold=float(generation.get("weak_rerank_threshold", -2.0)),
            query_rewrite=bool(generation.get("query_rewrite", True)),
            query_rewrite_max_history_turns=int(
                generation.get("query_rewrite_max_history_turns", 4)
            ),
            task_classification=bool(generation.get("task_classification", True)),
            query_prepare=str(generation.get("query_prepare", "merged")),
            openai_base_url=os.environ.get(
                "EE_WIKI_OPENAI_BASE_URL",
                str(generation.get("openai_base_url", "http://127.0.0.1:8000/v1")),
            ),
            openai_model=os.environ.get(
                "EE_WIKI_OPENAI_MODEL",
                str(generation.get("openai_model", "")),
            ),
            openai_api_key=os.environ.get(
                "EE_WIKI_OPENAI_API_KEY",
                generation.get("openai_api_key"),
            ),
            inline_citation_images=bool(generation.get("inline_citation_images", True)),
            max_inline_images=int(generation.get("max_inline_images", 4)),
            scope_inference=bool(generation.get("scope_inference", True)),
            scope_inference_mode=str(generation.get("scope_inference_mode", "merged")),
            show_elapsed_time=bool(generation.get("show_elapsed_time", False)),
        ),
        api=ApiConfig(
            host=str(api.get("host", "0.0.0.0")),
            port=int(api.get("port", 8080)),
            warmup_on_startup=bool(api.get("warmup_on_startup", False)),
            public_base_url=api.get("public_base_url"),
            request_timeout_seconds=_optional_positive_int(
                api.get("request_timeout_seconds", 300)
            ),
            max_concurrent_ingest_jobs=max(
                1, int(api.get("max_concurrent_ingest_jobs", 1))
            ),
            ingest_api_key=_optional_env_secret("EE_WIKI_INGEST_API_KEY"),
            concurrency=ApiConcurrencyConfig(
                max_concurrent=int(concurrency.get("max_concurrent", 1)),
                max_queue_depth=int(concurrency.get("max_queue_depth", 8)),
                retry_after_seconds=int(concurrency.get("retry_after_seconds", 15)),
            ),
        ),
    )
    logger.debug("Loaded config from %s (raw_dir=%s)", path, config.raw_dir)
    return config


