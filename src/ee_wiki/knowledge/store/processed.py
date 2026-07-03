"""Write ingested documents to the processed mirror under ``data/processed/``."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.fingerprint import raw_fingerprint
from ee_wiki.common.logging import get_logger
from ee_wiki.common.metadata_schema import validate_metadata_dict
from ee_wiki.common.serialization import metadata_to_dict
from ee_wiki.common.types import DataLayoutConfig, Metadata, StandardDocument
from ee_wiki.ingestion.processed_paths import resolve_processed_paths

logger = get_logger(__name__)


class ProcessedStoreError(EEWikiError):
    """Failed to write a document to the processed mirror."""


@dataclass(frozen=True)
class ProcessedPaths:
    """Output paths for a persisted processed document."""

    content_path: Path
    metadata_path: Path


def _target_file_label(
    content_path: Path,
    processed_dir: Path,
    repo_root: Path | None,
) -> str:
    relative = content_path.resolve().relative_to(processed_dir.resolve())
    if repo_root is not None:
        try:
            processed_prefix = processed_dir.resolve().relative_to(repo_root.resolve())
            return str(processed_prefix / relative)
        except ValueError:
            pass
    return str(Path("data/processed") / relative)


def write_processed_document(
    document: StandardDocument,
    raw_path: Path,
    layout: DataLayoutConfig,
    *,
    repo_root: Path | None = None,
    content_extension: str | None = None,
) -> ProcessedPaths:
    """Write document content and metadata sidecar mirroring ``data/raw/`` layout.

    The sidecar records ``source_mtime`` and ``source_size`` for incremental ingest.

    Args:
        document: Parsed standard document to persist.
        raw_path: Original file path under ``layout.raw_dir``.
        layout: Data layout with ``processed_dir`` and ``raw_dir``.
        repo_root: Optional repository root for path labels in metadata.
        content_extension: Optional processed file suffix (e.g. ``\".md\"`` for PDF sources).

    Returns:
        Paths written for content and metadata sidecar.

    Raises:
        ProcessedStoreError: If the raw path is outside ``raw_dir`` or write fails.
    """
    content_path, metadata_path = resolve_processed_paths(
        raw_path,
        layout,
        content_extension=content_extension,
    )
    target_file = _target_file_label(content_path, layout.processed_dir, repo_root)
    fingerprint = raw_fingerprint(raw_path)

    metadata: Metadata = replace(
        document.metadata,
        target_file=target_file,
        source_mtime=fingerprint.mtime,
        source_size=fingerprint.size,
    )

    paths = ProcessedPaths(content_path=content_path, metadata_path=metadata_path)
    metadata_payload = metadata_to_dict(metadata)
    if repo_root is not None:
        validate_metadata_dict(metadata_payload, repo_root=repo_root)
    try:
        content_path.parent.mkdir(parents=True, exist_ok=True)
        content_path.write_text(document.content, encoding="utf-8")
        metadata_path.write_text(
            json.dumps(metadata_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ProcessedStoreError(f"Failed to write processed document: {content_path}") from exc

    logger.info("Wrote processed mirror: %s", content_path.relative_to(layout.processed_dir))
    return paths
