"""Ingestion pipeline: parse raw files and write processed mirror."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.config import AppConfig, load_config
from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import StandardDocument
from ee_wiki.ingestion.parsers.markdown import MARKDOWN_SUFFIXES, parse_markdown
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
    if suffix in MARKDOWN_SUFFIXES:
        document = parse_markdown(path, layout, repo_root=config.repo_root)
    elif suffix in TEXT_SUFFIXES:
        document = parse_markdown(path, layout, repo_root=config.repo_root)
    else:
        raise IngestionError(f"Unsupported file type for V1 ingest: {path.suffix} ({path.name})")

    processed = write_processed_document(
        document,
        path,
        layout,
        repo_root=config.repo_root,
    )
    return IngestResult(raw_path=path, document=document, processed=processed)


def ingest_path(
    target: Path,
    config: AppConfig | None = None,
) -> list[IngestResult]:
    """Ingest a single file or all supported files under a directory.

    Args:
        target: File or directory path. Directories are walked recursively.
        config: Optional pre-loaded config; loaded from repo when omitted.

    Returns:
        List of ingest results in walk order.

    Raises:
        IngestionError: If the target does not exist or no files were ingested.
    """
    app_config = config or load_config()
    path = target.resolve()

    if not path.exists():
        raise IngestionError(f"Path does not exist: {path}")

    files: list[Path]
    if path.is_file():
        files = [path]
    else:
        files = sorted(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file()
            and not candidate.name.startswith(".")
            and candidate.suffix.lower() in (MARKDOWN_SUFFIXES | TEXT_SUFFIXES)
        )

    if not files:
        raise IngestionError(f"No ingestible files found under: {path}")

    results: list[IngestResult] = []
    for file_path in files:
        try:
            results.append(ingest_file(file_path, app_config))
        except IngestionError:
            raise
        except EEWikiError as exc:
            raise IngestionError(f"Failed to ingest {file_path}: {exc}") from exc

    logger.info("Ingested %d file(s) from %s", len(results), path)
    return results
