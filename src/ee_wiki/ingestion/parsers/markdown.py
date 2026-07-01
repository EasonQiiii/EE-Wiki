"""Parse Markdown files into :class:`StandardDocument`."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.path_metadata import parse_path_metadata

logger = get_logger(__name__)

MARKDOWN_SUFFIXES = {".md", ".markdown"}


class MarkdownParserError(EEWikiError):
    """Failed to parse a Markdown source file."""


def normalize_markdown(text: str) -> str:
    """Normalize line endings and trim trailing document whitespace.

    Args:
        text: Raw file contents.

    Returns:
        Normalized Markdown body.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip() + "\n"


def parse_markdown(
    raw_path: Path,
    layout: DataLayoutConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Read a Markdown file and build a :class:`StandardDocument`.

    Args:
        raw_path: Path to a ``.md`` or ``.markdown`` file under ``layout.raw_dir``.
        layout: Data layout configuration for path-derived metadata.
        repo_root: Optional repository root for ``source_file`` labels.

    Returns:
        Parsed document with normalized content and metadata.

    Raises:
        MarkdownParserError: If the file cannot be read or parsed.
    """
    try:
        content = raw_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MarkdownParserError(f"Cannot read Markdown file: {raw_path}") from exc
    except UnicodeDecodeError as exc:
        raise MarkdownParserError(f"Markdown file is not valid UTF-8: {raw_path}") from exc

    metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    document = StandardDocument(
        content=normalize_markdown(content),
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    logger.info(
        "Parsed Markdown %s (%d chars, title=%s)",
        metadata.source_file,
        len(document.content),
        metadata.title,
    )
    return document
