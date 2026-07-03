"""Parse legacy binary Word documents (``.doc``) via LibreOffice."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.prose_pdf import parse_prose_pdf
from ee_wiki.ingestion.parsers.word.errors import WordParserError
from ee_wiki.ingestion.parsers.word.libreoffice import (
    LibreOfficeError,
    convert_to_pdf,
    resolve_soffice_path,
)
from ee_wiki.ingestion.path_metadata import parse_path_metadata

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig, WordConfig

logger = get_logger(__name__)


def parse_legacy_doc(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    word_config: WordConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Convert a legacy ``.doc`` to PDF and reuse the prose PDF text pipeline.

    Args:
        raw_path: Path to a ``.doc`` file under ``layout.raw_dir``.
        layout: Data layout configuration for path-derived metadata.
        config: Application configuration (``prose_pdf`` settings for OCR).
        word_config: Word ingest settings (LibreOffice path).
        repo_root: Optional repository root for ``source_file`` labels.

    Returns:
        Parsed document with Markdown content and metadata from the original ``.doc``.

    Raises:
        WordParserError: If LibreOffice or PDF extraction fails.
    """
    metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    try:
        soffice = resolve_soffice_path(word_config.libreoffice_path)
    except LibreOfficeError as exc:
        raise WordParserError(str(exc)) from exc

    try:
        with tempfile.TemporaryDirectory(prefix="ee-wiki-doc-") as tmp:
            pdf_path = convert_to_pdf(
                raw_path,
                soffice=soffice,
                out_dir=Path(tmp),
            )
            interim = parse_prose_pdf(
                pdf_path,
                layout,
                config,
                repo_root=repo_root,
                metadata=metadata,
            )
    except LibreOfficeError as exc:
        raise WordParserError(str(exc)) from exc

    if not interim.content.strip():
        raise WordParserError(f".doc produced no text after PDF conversion: {raw_path}")

    document = StandardDocument(
        content=interim.content,
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    logger.info(
        "Parsed .doc %s via LibreOffice (%d chars, title=%s)",
        metadata.source_file,
        len(document.content),
        metadata.title,
    )
    return document
