"""Parse Apple iWork documents on macOS via Keynote/Numbers export."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.iwork.errors import IworkParserError
from ee_wiki.ingestion.parsers.iwork.keynote import parse_keynote
from ee_wiki.ingestion.parsers.iwork.numbers import parse_numbers

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig, IworkConfig

KEYNOTE_SUFFIXES = {".key"}
NUMBERS_SUFFIXES = {".numbers"}
IWORK_SUFFIXES = KEYNOTE_SUFFIXES | NUMBERS_SUFFIXES

__all__ = [
    "IWORK_SUFFIXES",
    "IworkParserError",
    "KEYNOTE_SUFFIXES",
    "NUMBERS_SUFFIXES",
    "iwork_ingest_active",
    "parse_keynote",
    "parse_numbers",
]


def iwork_ingest_active(config: IworkConfig) -> bool:
    """Return whether ``.key`` / ``.numbers`` ingest should run on this host.

    Args:
        config: iWork ingest settings from application config.

    Returns:
        ``True`` on macOS when iWork ingest is enabled in config.
    """
    return sys.platform == "darwin" and config.enabled


def parse_iwork(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Dispatch ``.key`` or ``.numbers`` to the appropriate iWork parser.

    Args:
        raw_path: Path under ``layout.raw_dir``.
        layout: Data layout configuration.
        config: Application configuration.
        repo_root: Optional repository root for metadata labels.

    Returns:
        Parsed standard document.

    Raises:
        IworkParserError: If the suffix is unsupported or parsing fails.
    """
    suffix = raw_path.suffix.lower()
    if suffix in KEYNOTE_SUFFIXES:
        return parse_keynote(raw_path, layout, config, repo_root=repo_root)
    if suffix in NUMBERS_SUFFIXES:
        return parse_numbers(raw_path, layout, config, repo_root=repo_root)
    raise IworkParserError(f"Unsupported iWork suffix: {raw_path.suffix}")
