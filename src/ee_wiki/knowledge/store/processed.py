"""Write ingested documents to the processed mirror under ``data/processed/``."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import metadata_to_dict
from ee_wiki.common.types import DataLayoutConfig, Metadata, StandardDocument

logger = get_logger(__name__)


class ProcessedStoreError(EEWikiError):
    """Failed to write a document to the processed mirror."""


@dataclass(frozen=True)
class ProcessedPaths:
    """Output paths for a persisted processed document."""

    content_path: Path
    metadata_path: Path


def _relative_raw_path(raw_path: Path, raw_dir: Path) -> Path:
    try:
        return raw_path.resolve().relative_to(raw_dir.resolve())
    except ValueError as exc:
        raise ProcessedStoreError(
            f"Cannot mirror path outside raw_dir ({raw_dir}): {raw_path}"
        ) from exc


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
) -> ProcessedPaths:
    """Write document content and metadata sidecar mirroring ``data/raw/`` layout.

    Example::

        data/raw/logan/p1/note/manual.md
            → data/processed/logan/p1/note/manual.md
            → data/processed/logan/p1/note/manual.meta.json

    The sidecar includes ``source_file`` (raw provenance) and ``target_file``
    (normalized content path for chunking and retrieval).

    Args:
        document: Parsed standard document to persist.
        raw_path: Original file path under ``layout.raw_dir``.
        layout: Data layout with ``processed_dir`` and ``raw_dir``.
        repo_root: Optional repository root for path labels in metadata.

    Returns:
        Paths written for content and metadata sidecar.

    Raises:
        ProcessedStoreError: If the raw path is outside ``raw_dir`` or write fails.
    """
    relative = _relative_raw_path(raw_path, layout.raw_dir)
    content_path = layout.processed_dir / relative
    metadata_path = content_path.with_suffix(f"{content_path.suffix}.meta.json")
    target_file = _target_file_label(content_path, layout.processed_dir, repo_root)

    metadata: Metadata = replace(document.metadata, target_file=target_file)

    try:
        content_path.parent.mkdir(parents=True, exist_ok=True)
        content_path.write_text(document.content, encoding="utf-8")
        metadata_path.write_text(
            json.dumps(metadata_to_dict(metadata), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ProcessedStoreError(f"Failed to write processed document: {content_path}") from exc

    logger.info("Wrote processed mirror: %s", content_path.relative_to(layout.processed_dir))
    return ProcessedPaths(content_path=content_path, metadata_path=metadata_path)
