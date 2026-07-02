"""Incremental ingest checks using raw file fingerprints."""

from __future__ import annotations

import json
from pathlib import Path

from ee_wiki.common.fingerprint import raw_fingerprint
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.parsers.markdown import MARKDOWN_SUFFIXES
from ee_wiki.ingestion.parsers.pdf_common import PDF_SUFFIXES
from ee_wiki.ingestion.path_metadata import PathMetadataError, parse_path_metadata
from ee_wiki.ingestion.processed_paths import resolve_processed_paths

logger = get_logger(__name__)

TEXT_SUFFIXES = {".txt"}


def expected_content_extension(raw_path: Path, layout: DataLayoutConfig) -> str | None:
    """Return processed content suffix when it differs from the raw suffix.

    Args:
        raw_path: Raw file path.
        layout: Data layout for path metadata parsing.

    Returns:
        ``\".md\"`` for PDF sources, otherwise ``None``.
    """
    if raw_path.suffix.lower() not in PDF_SUFFIXES:
        return None
    try:
        parse_path_metadata(raw_path, layout)
    except PathMetadataError:
        return None
    return ".md"


def is_supported_raw_file(raw_path: Path) -> bool:
    """Return whether ``raw_path`` has a supported ingest suffix."""
    suffix = raw_path.suffix.lower()
    return suffix in MARKDOWN_SUFFIXES | TEXT_SUFFIXES | PDF_SUFFIXES


def is_ingestible_raw_file(raw_path: Path, layout: DataLayoutConfig) -> bool:
    """Return whether the file can be ingested (supported type and valid layout)."""
    if not is_supported_raw_file(raw_path):
        return False
    if raw_path.suffix.lower() in PDF_SUFFIXES:
        try:
            parse_path_metadata(raw_path, layout)
        except PathMetadataError:
            return False
        return True
    try:
        parse_path_metadata(raw_path, layout)
    except PathMetadataError:
        return False
    return True


def needs_ingest(
    raw_path: Path,
    layout: DataLayoutConfig,
    *,
    force: bool = False,
) -> bool:
    """Return ``True`` when a raw file should be ingested.

    Skips files whose sidecar records the same ``source_mtime`` and ``source_size``.

    Args:
        raw_path: Raw file under ``layout.raw_dir``.
        layout: Data layout configuration.
        force: When ``True``, always re-ingest.

    Returns:
        Whether ingest should run for this file.
    """
    if force:
        return True

    content_extension = expected_content_extension(raw_path, layout)
    content_path, metadata_path = resolve_processed_paths(
        raw_path,
        layout,
        content_extension=content_extension,
    )
    if not content_path.is_file() or not metadata_path.is_file():
        return True

    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Invalid metadata sidecar, re-ingesting: %s", metadata_path)
        return True

    fingerprint = raw_fingerprint(raw_path)
    recorded_mtime = meta.get("source_mtime")
    recorded_size = meta.get("source_size")
    if recorded_mtime is None or recorded_size is None:
        return True

    if float(recorded_mtime) == fingerprint.mtime and int(recorded_size) == fingerprint.size:
        logger.debug("Skip unchanged raw file: %s", raw_path)
        return False
    return True


def collect_raw_files(raw_dir: Path, layout: DataLayoutConfig) -> list[Path]:
    """Walk ``raw_dir`` and return ingestible files in stable order."""
    if not raw_dir.is_dir():
        return []

    files: list[Path] = []
    for candidate in sorted(raw_dir.rglob("*")):
        if not candidate.is_file() or candidate.name.startswith("."):
            continue
        if not is_ingestible_raw_file(candidate, layout):
            continue
        files.append(candidate)
    return files
