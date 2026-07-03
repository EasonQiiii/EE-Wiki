"""Parse Microsoft Word documents into :class:`StandardDocument`."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.word.docx import parse_docx
from ee_wiki.ingestion.parsers.word.errors import WordParserError
from ee_wiki.ingestion.parsers.word.legacy_doc import parse_legacy_doc

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

WORD_DOCX_SUFFIXES = {".docx"}
WORD_DOC_SUFFIXES = {".doc"}
WORD_SUFFIXES = WORD_DOC_SUFFIXES | WORD_DOCX_SUFFIXES

__all__ = [
    "WORD_DOC_SUFFIXES",
    "WORD_DOCX_SUFFIXES",
    "WORD_SUFFIXES",
    "WordParserError",
    "parse_word",
]


def parse_word(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Parse a ``.doc`` or ``.docx`` file into Markdown.

    Args:
        raw_path: Path under ``layout.raw_dir``.
        layout: Data layout configuration.
        config: Application configuration.
        repo_root: Optional repository root for metadata labels.

    Returns:
        Parsed standard document.

    Raises:
        WordParserError: If the suffix is unsupported or parsing fails.
    """
    suffix = raw_path.suffix.lower()
    if suffix in WORD_DOCX_SUFFIXES:
        return parse_docx(raw_path, layout, repo_root=repo_root)
    if suffix in WORD_DOC_SUFFIXES:
        return parse_legacy_doc(
            raw_path,
            layout,
            config,
            config.word,
            repo_root=repo_root,
        )
    raise WordParserError(f"Unsupported Word suffix: {raw_path.suffix}")
