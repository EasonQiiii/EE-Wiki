"""Remove processed mirror files whose raw sources were deleted."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig

logger = get_logger(__name__)


@dataclass(frozen=True)
class RemovedProcessed:
    """Processed artifacts removed because the raw source is gone."""

    content_path: Path
    metadata_path: Path
    source_file: str


def raw_path_from_source_file(source_file: str, layout: DataLayoutConfig) -> Path:
    """Map a ``source_file`` metadata label back to an absolute raw path."""
    path = Path(source_file)
    parts = path.parts
    if len(parts) >= 2 and parts[0] == "data" and parts[1] == "raw":
        return layout.raw_dir / Path(*parts[2:])
    return layout.raw_dir / path


def _content_path_for_meta(meta_path: Path) -> Path:
    name = meta_path.name
    if not name.endswith(".meta.json"):
        raise ValueError(f"Not a metadata sidecar: {meta_path}")
    return meta_path.with_name(name[: -len(".meta.json")])


def _processed_scan_root(layout: DataLayoutConfig, raw_scope: Path) -> Path:
    """Return the processed subtree to scan for orphans."""
    resolved = raw_scope.resolve()
    if resolved.is_file():
        raise ValueError("raw_scope must be a directory")

    try:
        relative = resolved.relative_to(layout.raw_dir.resolve())
    except ValueError:
        return layout.processed_dir
    if relative in {Path("."), Path("")}:
        return layout.processed_dir
    return layout.processed_dir / relative


def _prune_empty_dirs(root: Path, stop_at: Path) -> None:
    """Remove empty directories up to ``stop_at`` (inclusive boundary)."""
    current = root.resolve()
    stop = stop_at.resolve()
    while current != stop and stop in current.parents and current.is_dir():
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def cleanup_orphaned_processed(
    layout: DataLayoutConfig,
    *,
    raw_scope: Path,
) -> list[RemovedProcessed]:
    """Delete processed content/meta when the corresponding raw file no longer exists.

    Args:
        layout: Data layout with ``raw_dir`` and ``processed_dir``.
        raw_scope: Raw directory that bounds the cleanup scan (usually the ingest target).

    Returns:
        List of removed processed artifacts.
    """
    processed_root = _processed_scan_root(layout, raw_scope)
    if not processed_root.is_dir():
        return []

    removed: list[RemovedProcessed] = []
    for meta_path in sorted(processed_root.rglob("*.meta.json")):
        if not meta_path.is_file():
            continue

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Skipping unreadable metadata sidecar: %s", meta_path)
            continue

        source_file = meta.get("source_file")
        if not source_file:
            continue

        raw_path = raw_path_from_source_file(str(source_file), layout)
        if raw_path.is_file():
            continue

        content_path = _content_path_for_meta(meta_path)
        if content_path.is_file():
            content_path.unlink()
        if meta_path.is_file():
            meta_path.unlink()

        removed.append(
            RemovedProcessed(
                content_path=content_path,
                metadata_path=meta_path,
                source_file=str(source_file),
            )
        )
        logger.info("Removed orphaned processed mirror for missing raw: %s", source_file)
        _prune_empty_dirs(content_path.parent, layout.processed_dir)

    return removed
