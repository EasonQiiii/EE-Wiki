"""Incremental ingest checks using raw file fingerprints."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.fingerprint import raw_fingerprint
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig
from ee_wiki.ingestion.parsers.excel import EXCEL_SUFFIXES
from ee_wiki.ingestion.parsers.iwork import IWORK_SUFFIXES
from ee_wiki.ingestion.parsers.markdown import MARKDOWN_SUFFIXES
from ee_wiki.ingestion.parsers.pdf_common import PDF_SUFFIXES
from ee_wiki.ingestion.parsers.word import WORD_SUFFIXES
from ee_wiki.ingestion.path_metadata import PathMetadataError, parse_path_metadata
from ee_wiki.ingestion.processed_paths import resolve_processed_paths

logger = get_logger(__name__)

TEXT_SUFFIXES = {".txt"}


@dataclass(frozen=True)
class RawFileWarning:
    """A raw file under scope that was not ingested (unsupported or deferred)."""

    raw_path: Path
    message: str


def _relative_raw_path(raw_path: Path, raw_dir: Path) -> Path | str:
    """Return a path label relative to ``raw_dir`` when possible."""
    try:
        return raw_path.resolve().relative_to(raw_dir.resolve())
    except ValueError:
        return raw_path.name


def expected_content_extension(raw_path: Path, layout: DataLayoutConfig) -> str | None:
    """Return processed content suffix when it differs from the raw suffix.

    Args:
        raw_path: Raw file path.
        layout: Data layout for path metadata parsing.

    Returns:
        ``\".md\"`` for PDF and iWork sources, otherwise ``None``.
    """
    convertible_suffixes = PDF_SUFFIXES | EXCEL_SUFFIXES | WORD_SUFFIXES | IWORK_SUFFIXES
    if raw_path.suffix.lower() not in convertible_suffixes:
        return None
    try:
        parse_path_metadata(raw_path, layout)
    except PathMetadataError:
        return None
    return ".md"


def is_supported_raw_file(raw_path: Path, *, iwork_enabled: bool = False) -> bool:
    """Return whether ``raw_path`` has a supported ingest suffix."""
    suffix = raw_path.suffix.lower()
    supported = MARKDOWN_SUFFIXES | TEXT_SUFFIXES | PDF_SUFFIXES | EXCEL_SUFFIXES | WORD_SUFFIXES
    if iwork_enabled:
        supported |= IWORK_SUFFIXES
    return suffix in supported


def is_ingestible_raw_file(
    raw_path: Path,
    layout: DataLayoutConfig,
    *,
    iwork_enabled: bool = False,
) -> bool:
    """Return whether the file can be ingested (supported type and valid layout)."""
    if not is_supported_raw_file(raw_path, iwork_enabled=iwork_enabled):
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


def log_skipped_raw_files(
    raw_scope: Path,
    layout: DataLayoutConfig,
    *,
    iwork_enabled: bool = False,
) -> list[RawFileWarning]:
    """Log deferred and unsupported raw files discovered under ``raw_scope``.

    Args:
        raw_scope: File or directory under ``layout.raw_dir`` to scan.
        layout: Data layout with ``raw_dir`` for relative log labels.
        iwork_enabled: When ``False``, ``.key`` / ``.numbers`` are logged as deferred.

    Returns:
        Warning entries for files that were not ingested.
    """
    resolved = raw_scope.resolve()
    if resolved.is_file():
        candidates = [resolved]
    elif resolved.is_dir():
        candidates = sorted(resolved.rglob("*"))
    else:
        return []

    warnings: list[RawFileWarning] = []
    for candidate in candidates:
        if not candidate.is_file() or candidate.name.startswith("."):
            continue
        suffix = candidate.suffix.lower()
        if not suffix:
            continue
        rel = _relative_raw_path(candidate, layout.raw_dir)
        if suffix in IWORK_SUFFIXES and not iwork_enabled:
            if sys.platform != "darwin":
                message = (
                    f"requires macOS with Keynote/Numbers ({suffix})"
                )
            else:
                message = (
                    "set ingestion.iwork.enabled: true "
                    f"to ingest {suffix} files"
                )
            logger.warning("Skipping iWork format %s (%s): %s", suffix, rel, message)
            warnings.append(RawFileWarning(raw_path=candidate, message=message))
        elif not is_supported_raw_file(candidate, iwork_enabled=iwork_enabled):
            message = "unsupported raw file format"
            logger.warning("Skipping unsupported raw file: %s", rel)
            warnings.append(RawFileWarning(raw_path=candidate, message=message))
    return warnings


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


def collect_raw_files(
    raw_dir: Path,
    layout: DataLayoutConfig,
    *,
    iwork_enabled: bool = False,
) -> list[Path]:
    """Walk ``raw_dir`` and return ingestible files in stable order."""
    if not raw_dir.is_dir():
        return []

    files: list[Path] = []
    for candidate in sorted(raw_dir.rglob("*")):
        if not candidate.is_file() or candidate.name.startswith("."):
            continue
        if not is_ingestible_raw_file(candidate, layout, iwork_enabled=iwork_enabled):
            continue
        files.append(candidate)
    return files
