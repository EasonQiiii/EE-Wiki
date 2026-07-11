"""Abstract interfaces for document parsers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ee_wiki.common.types import DataLayoutConfig, StandardDocument


class DocumentParser(Protocol):
    """Parse a raw file path into a :class:`StandardDocument`."""

    def parse(
        self,
        raw_path: Path,
        layout: DataLayoutConfig,
        *,
        repo_root: Path | None = None,
    ) -> StandardDocument:
        """Parse one raw document under ``data/raw/``.

        Args:
            raw_path: Absolute or repo-relative path to the source file.
            layout: Data layout configuration for path metadata and output paths.
            repo_root: Optional repository root for relative path resolution.

        Returns:
            Normalized Markdown body with validated metadata.
        """
        ...
