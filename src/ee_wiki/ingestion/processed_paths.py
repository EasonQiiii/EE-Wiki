"""Path helpers for the processed mirror layout."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.types import DataLayoutConfig


class ProcessedPathError(EEWikiError):
    """Failed to resolve processed mirror paths."""


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
