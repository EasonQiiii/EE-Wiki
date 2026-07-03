"""Parse Office Open XML Word documents (``.docx``)."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.markdown import normalize_markdown
from ee_wiki.ingestion.parsers.word.errors import WordParserError
from ee_wiki.ingestion.path_metadata import parse_path_metadata

logger = get_logger(__name__)


def parse_docx(
    raw_path: Path,
    layout: DataLayoutConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Read a ``.docx`` file and build a :class:`StandardDocument`.

    Args:
        raw_path: Path to a ``.docx`` file under ``layout.raw_dir``.
        layout: Data layout configuration for path-derived metadata.
        repo_root: Optional repository root for ``source_file`` labels.

    Returns:
        Parsed document with Markdown content and metadata.

    Raises:
        WordParserError: If mammoth is missing or conversion fails.
    """
    try:
        import mammoth
    except ImportError as exc:
        raise WordParserError(
            "mammoth is required for .docx ingest; install with pip install 'ee-wiki[ml]'"
        ) from exc

    metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    try:
        with raw_path.open("rb") as handle:
            result = mammoth.convert_to_markdown(handle)
    except OSError as exc:
        raise WordParserError(f"Cannot read Word file: {raw_path}") from exc
    except Exception as exc:
        raise WordParserError(f"Failed to parse .docx: {raw_path}") from exc

    for message in result.messages:
        logger.info("mammoth (%s): %s", raw_path.name, message)

    body = result.value.strip()
    if not body:
        raise WordParserError(f".docx produced no text: {raw_path}")

    content = normalize_markdown(f"# {metadata.title}\n\n{body}\n")
    document = StandardDocument(
        content=content,
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    logger.info(
        "Parsed .docx %s (%d chars, title=%s)",
        metadata.source_file,
        len(document.content),
        metadata.title,
    )
    return document
