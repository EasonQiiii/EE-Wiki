"""Filesystem helpers for FA cache and export artifacts."""

from __future__ import annotations

import re
from pathlib import Path

_RADAR_DIGITS = re.compile(r"(\d{5,})")


def normalize_radar_id(value: str) -> str:
    """Normalize ``rdar://``, ``radar``, or bare ids to digits-only.

    Args:
        value: User- or API-supplied Radar identifier.

    Returns:
        Digits-only Radar id.

    Raises:
        ValueError: If no numeric id can be extracted.
    """
    text = value.strip()
    match = _RADAR_DIGITS.search(text)
    if not match:
        raise ValueError(f"Could not parse Radar id from {value!r}")
    return match.group(1)


def fa_cache_dir(cache_root: Path, radar_id: str) -> Path:
    """Return ``data/cache/fa/{radar_id}/`` (not created)."""
    return cache_root / "fa" / normalize_radar_id(radar_id)


def fa_export_dir(exports_root: Path, radar_id: str) -> Path:
    """Return ``data/exports/fa/{radar_id}/`` (not created)."""
    return exports_root / "fa" / normalize_radar_id(radar_id)


def fa_summary_path(exports_root: Path, radar_id: str) -> Path:
    """Return the canonical Keynote path for an FA summary."""
    return fa_export_dir(exports_root, radar_id) / "FA_summary.key"


def fa_summary_download_rel(radar_id: str) -> str:
    """Relative path under exports root for download URLs."""
    return f"fa/{normalize_radar_id(radar_id)}/FA_summary.key"
