"""Raw file fingerprint helpers for incremental ingest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RawFingerprint:
    """Raw source file identity for incremental ingest."""

    mtime: float
    size: int


def raw_fingerprint(raw_path: Path) -> RawFingerprint:
    """Read modification time and size from a raw file."""
    stat = raw_path.stat()
    return RawFingerprint(mtime=stat.st_mtime, size=stat.st_size)
