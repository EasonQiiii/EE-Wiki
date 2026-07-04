"""Path helpers for the processed mirror layout."""

from __future__ import annotations

import re
from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.types import DataLayoutConfig


class ProcessedPathError(EEWikiError):
    """Failed to resolve processed mirror paths."""


def _filename_slug(stem: str) -> str:
    """Normalize a filename stem into a filesystem-safe slug."""
    slug = stem.lower().replace(" ", "_")
    return re.sub(r"[^\w\-]+", "_", slug).strip("_") or "document"


def relative_raw_path(raw_path: Path, raw_dir: Path) -> Path:
    """Return ``raw_path`` relative to ``raw_dir``."""
    try:
        return raw_path.resolve().relative_to(raw_dir.resolve())
    except ValueError as exc:
        raise ProcessedPathError(
            f"Cannot mirror path outside raw_dir ({raw_dir}): {raw_path}"
        ) from exc


def resolve_processed_paths(
    raw_path: Path,
    layout: DataLayoutConfig,
    *,
    content_extension: str | None = None,
) -> tuple[Path, Path]:
    """Resolve processed content and metadata sidecar paths for a raw file."""
    relative = relative_raw_path(raw_path, layout.raw_dir)
    if content_extension:
        relative = relative.with_suffix(content_extension)
    content_path = layout.processed_dir / relative
    metadata_path = content_path.with_suffix(f"{content_path.suffix}.meta.json")
    return content_path, metadata_path


def resolve_images_dir(
    content_path: Path,
    *,
    images_rel_prefix: str = "images",
) -> Path:
    """Derive the images directory for a processed content file.

    The convention mirrors both schematic and prose PDF pipelines::

        data/processed/{project}/{build}/{type}/images/{slug}/

    where *slug* is derived from the content file stem.

    Args:
        content_path: Path to the ``.md`` content file.
        images_rel_prefix: Subdirectory name (default ``images``).

    Returns:
        Absolute path to the images directory (may not exist yet).
    """
    slug = _filename_slug(content_path.stem)
    return content_path.parent / images_rel_prefix / slug
