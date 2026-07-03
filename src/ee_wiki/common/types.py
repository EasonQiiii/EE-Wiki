"""Core data types shared across EE-Wiki modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Metadata:
    """Document metadata derived from path and ingestion."""

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
    keywords: list[str] = field(default_factory=list)
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
    """Pre-retrieval constraints for project, build, and document type."""

    project: str | None = None
    build: str | None = None
    document_type: str | None = None


@dataclass(frozen=True)
class DataLayoutConfig:
    """Path segment naming for raw data layout."""

    enterprise_project: str
    project_shared_build: str
    document_type_folders: dict[str, str]
    raw_dir: Path
    processed_dir: Path


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
