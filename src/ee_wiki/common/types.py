"""Core data types shared across EE-Wiki modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PageMetadata:
    """Per-page schematic metadata for chunk-level retrieval."""

    page: int
    major_components: list[str] = field(default_factory=list)
    nets: list[str] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Metadata:
    """Document metadata derived from path and ingestion.

    Scope is a three-level hierarchy: ``product`` (top program/product line),
    ``project`` (a program within a product), and ``build`` (a specific
    hardware revision). See ADR 0011 and README Raw Data Layout.
    """

    product: str
    project: str
    build: str
    document_type: str
    title: str
    source_file: str
    target_file: str = ""
    source_mtime: float = 0.0
    source_size: int = 0
    page: int = 0
    major_components: list[str] | None = None
    nets: list[str] | None = None
    interfaces: list[str] | None = None
    pages: list[PageMetadata] | None = None
    keywords: list[str] = field(default_factory=list)
    supply_voltage: list[str] | None = None
    pin_count: int | None = None
    package: str | None = None
    # Failure-analysis / debug-case fields (fa/ → failure_analysis)
    case_id: str | None = None
    symptom: str | None = None
    suspected_nets: list[str] | None = None
    suspected_parts: list[str] | None = None
    steps: list[str] | None = None
    root_cause: str | None = None
    case_citations: list[str] | None = None
    version: str = ""


@dataclass(frozen=True)
class StandardDocument:
    """Normalized parser output before persistence."""

    content: str
    metadata: Metadata
    source_ref: str


@dataclass(frozen=True)
class Citation:
    """Provenance for a retrieved context block."""

    source_file: str
    chunk_id: str
    page: int = 0
    excerpt: str = ""
    url: str = ""
    images: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chunk:
    """Indexed document segment used in retrieval."""

    chunk_id: str
    content: str
    metadata: Metadata
    citation: Citation
    heading_path: str = ""


@dataclass(frozen=True)
class RagAnswer:
    """Generated answer grounded in retrieved chunks."""

    answer: str
    citations: list[Citation]
    insufficient_context: bool = False


@dataclass(frozen=True)
class MetadataFilter:
    """Pre-retrieval constraints for product, project, build, and document type."""

    product: str | None = None
    project: str | None = None
    build: str | None = None
    document_type: str | None = None


@dataclass(frozen=True)
class DataLayoutConfig:
    """Path segment naming for raw data layout.

    The canonical hierarchy is ``{product}/{project}/{build}/{type}`` with two
    reserved words: ``enterprise_project`` (``global``) marks the enterprise
    library, and ``project_shared_build`` (``common``) marks a shared tier at
    either the project segment (product common) or the build segment (project
    common). See ADR 0011.
    """

    enterprise_project: str
    project_shared_build: str
    document_type_folders: dict[str, str]
    raw_dir: Path
    processed_dir: Path
    # Alternate names → EE-Wiki path slug (e.g. 甲方 H340 → 乙方 logan)
    project_aliases: dict[str, str] = field(default_factory=dict)

    @property
    def global_segment(self) -> str:
        """Reserved top segment for the enterprise-wide library (``global``)."""
        return self.enterprise_project

    @property
    def common_segment(self) -> str:
        """Reserved shared segment (``common``) for product/project common tiers."""
        return self.project_shared_build

    @property
    def reserved_segments(self) -> frozenset[str]:
        """Segment names that may not be used as ordinary product/project/build slugs."""
        return frozenset({self.enterprise_project, self.project_shared_build})


@dataclass(frozen=True)
class ModelsConfig:
    """Local model paths for offline ingestion and retrieval."""

    base_dir: Path
    layout_model: Path | None = None
    visual_model: Path | None = None
    embedding_model: Path | None = None
    reranker_model: Path | None = None
    llm_transformers_model: Path | None = None
    llm_mlx_model: Path | None = None

    def resolve(self, name: str | None) -> Path | None:
        if not name:
            return None
        path = Path(name)
        if path.is_absolute():
            return path
        return (self.base_dir / path).resolve()

    def resolve_llm_model(self, backend: str) -> Path | None:
        """Return the LLM path for ``generation.llm_backend``."""
        normalized = backend.casefold()
        if normalized == "mlx":
            return self.llm_mlx_model
        if normalized == "transformers":
            return self.llm_transformers_model
        return None

    @staticmethod
    def llm_config_key(backend: str) -> str:
        """YAML key name for the given ``generation.llm_backend`` value."""
        normalized = backend.casefold()
        if normalized == "mlx":
            return "llm_mlx_model"
        if normalized == "transformers":
            return "llm_transformers_model"
        return f"llm_{normalized}_model"
