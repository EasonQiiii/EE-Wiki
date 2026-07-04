"""Ingestion pipeline: parse raw files and write processed mirror."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from ee_wiki.common.config import AppConfig, load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import DATASHEET_DOCUMENT_TYPE, SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.common.types import StandardDocument
from ee_wiki.ingestion.cleanup import RemovedProcessed, cleanup_orphaned_processed
from ee_wiki.ingestion.keywords import extract_keywords
from ee_wiki.ingestion.parsers.datasheet_pdf import parse_datasheet_pdf
from ee_wiki.ingestion.parsers.excel import EXCEL_SUFFIXES, parse_excel
from ee_wiki.ingestion.parsers.markdown import MARKDOWN_SUFFIXES, parse_markdown
from ee_wiki.ingestion.parsers.pdf_common import PDF_SUFFIXES
from ee_wiki.ingestion.parsers.prose_pdf import parse_prose_pdf
from ee_wiki.ingestion.parsers.schematic_pdf import parse_schematic_pdf
from ee_wiki.ingestion.parsers.word import WORD_SUFFIXES, parse_word
from ee_wiki.ingestion.path_metadata import parse_path_metadata
from ee_wiki.ingestion.sync import (
    DEFERRED_SUFFIXES,
    collect_raw_files,
    expected_content_extension,
    is_ingestible_raw_file,
    is_supported_raw_file,
    log_skipped_raw_files,
    needs_ingest,
)
from ee_wiki.knowledge.store.processed import ProcessedPaths, write_processed_document

logger = get_logger(__name__)

TEXT_SUFFIXES = {".txt"}


class IngestionError(EEWikiError):
    """Ingestion failed for a raw document."""


@dataclass(frozen=True)
class IngestResult:
    """Outcome of ingesting one raw file."""

    raw_path: Path
    document: StandardDocument
    processed: ProcessedPaths


@dataclass(frozen=True)
class IngestRunResult:
    """Batch ingest outcome."""

    ingested: list[IngestResult] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    removed: list[RemovedProcessed] = field(default_factory=list)


def _enrich_keywords(document: StandardDocument) -> StandardDocument:
    """Extract engineering keywords from content and merge into metadata."""
    existing = document.metadata.keywords or []
    extracted = extract_keywords(document.content)
    merged = sorted(set(existing) | set(extracted))
    if merged == existing:
        return document
    new_meta = replace(document.metadata, keywords=merged)
    return StandardDocument(
        content=document.content,
        metadata=new_meta,
        source_ref=document.source_ref,
    )


def ingest_file(
    raw_path: Path,
    config: AppConfig,
) -> IngestResult:
    """Parse one raw file and write its processed mirror.

    Args:
        raw_path: File under ``config.raw_dir``.
        config: Application configuration.

    Returns:
        Ingest result with parsed document and output paths.

    Raises:
        IngestionError: If the file type is unsupported or ingestion fails.
    """
    path = raw_path.resolve()
    layout = config.data_layout

    if not path.is_file():
        raise IngestionError(f"Not a file: {path}")
    if path.name.startswith("."):
        raise IngestionError(f"Hidden files are skipped: {path}")

    suffix = path.suffix.lower()
    try:
        relative = path.relative_to(layout.raw_dir)
        logger.info("Ingesting: %s", relative)
        if suffix in MARKDOWN_SUFFIXES:
            document = parse_markdown(path, layout, repo_root=config.repo_root)
        elif suffix in TEXT_SUFFIXES:
            document = parse_markdown(path, layout, repo_root=config.repo_root)
        elif suffix in PDF_SUFFIXES:
            metadata = parse_path_metadata(path, layout, repo_root=config.repo_root)
            if metadata.document_type == SCHEMATIC_DOCUMENT_TYPE:
                document = parse_schematic_pdf(
                    path,
                    layout,
                    config,
                    repo_root=config.repo_root,
                )
            elif metadata.document_type == DATASHEET_DOCUMENT_TYPE:
                document = parse_datasheet_pdf(
                    path,
                    layout,
                    config,
                    repo_root=config.repo_root,
                )
            else:
                document = parse_prose_pdf(
                    path,
                    layout,
                    config,
                    repo_root=config.repo_root,
                )
        elif suffix in EXCEL_SUFFIXES:
            document = parse_excel(
                path,
                layout,
                config.excel,
                repo_root=config.repo_root,
            )
        elif suffix in WORD_SUFFIXES:
            document = parse_word(
                path,
                layout,
                config,
                repo_root=config.repo_root,
            )
        else:
            raise IngestionError(
                f"Unsupported file type for V1 ingest: {path.suffix} ({path.name})"
            )
    except EEWikiError as exc:
        raise IngestionError(f"Failed to ingest {path.name}: {exc}") from exc

    document = _enrich_keywords(document)

    processed = write_processed_document(
        document,
        path,
        layout,
        repo_root=config.repo_root,
        content_extension=expected_content_extension(path, layout),
    )
    return IngestResult(raw_path=path, document=document, processed=processed)


def ingest_path(
    target: Path | None = None,
    config: AppConfig | None = None,
    *,
    force: bool = False,
) -> IngestRunResult:
    """Ingest new or changed files under ``data/raw/``.

    When ``target`` is omitted, walks the configured ``raw_dir``. Files whose
    ``source_mtime`` and ``source_size`` match the existing sidecar are skipped.

    Args:
        target: Optional file or directory under ``data/raw/``. Defaults to ``raw_dir``.
        config: Optional pre-loaded config; loaded from repo when omitted.
        force: Re-ingest all files even when fingerprints match.

    Returns:
        Ingest and skip lists for the run.

    Raises:
        IngestionError: If the target path does not exist.
    """
    app_config = config or load_config()
    path = (target or app_config.raw_dir).resolve()
    layout = app_config.data_layout

    if not path.exists():
        raise IngestionError(f"Path does not exist: {path}")

    if path.is_file():
        suffix = path.suffix.lower()
        if suffix in DEFERRED_SUFFIXES:
            log_skipped_raw_files(path, layout)
            return IngestRunResult()
        if not is_supported_raw_file(path):
            log_skipped_raw_files(path, layout)
            return IngestRunResult()
        if not is_ingestible_raw_file(path, layout):
            raise IngestionError(
                f"Raw path does not match expected layout under {layout.raw_dir}: {path.name}"
            )
        files = [path]
        run_cleanup = False
    else:
        log_skipped_raw_files(path, layout)
        files = collect_raw_files(path, layout)
        run_cleanup = True

    removed = (
        cleanup_orphaned_processed(layout, raw_scope=path)
        if run_cleanup
        else []
    )

    if not files:
        logger.info("No ingestible files found under: %s", path)
        return IngestRunResult(removed=removed)

    ingested: list[IngestResult] = []
    skipped: list[Path] = []

    for file_path in files:
        if not needs_ingest(file_path, layout, force=force):
            skipped.append(file_path)
            logger.info("Skipped unchanged: %s", file_path.relative_to(layout.raw_dir))
            continue
        ingested.append(ingest_file(file_path, app_config))

    logger.info(
        "Ingest complete: %d ingested, %d skipped, %d removed under %s",
        len(ingested),
        len(skipped),
        len(removed),
        path,
    )
    return IngestRunResult(ingested=ingested, skipped=skipped, removed=removed)
