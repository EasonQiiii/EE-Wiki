"""Parse prose PDF files (note, sop, datasheet, …) into Markdown."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.pdf_common import PDF_SUFFIXES
from ee_wiki.ingestion.parsers.prose_pdf.extract import PageText, extract_page_text
from ee_wiki.ingestion.parsers.prose_pdf.language import (
    resolve_document_ocr_language,
    resolve_page_ocr_language,
)
from ee_wiki.ingestion.parsers.prose_pdf.tesseract_paths import resolve_tessdata_dir
from ee_wiki.ingestion.path_metadata import parse_path_metadata

try:
    import fitz
except ImportError:  # pragma: no cover - optional at import time
    fitz = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)


class ProsePdfParserError(EEWikiError):
    """Failed to parse a prose PDF."""


def _build_markdown(title: str, pages: list[PageText]) -> str:
    """Merge per-page text into a Markdown document with page headings."""
    sections: list[str] = [f"# {title}"]
    for page in pages:
        body = page.text.strip()
        if not body:
            continue
        sections.append(f"## Page {page.page}\n\n{body}")
    if len(sections) == 1:
        sections.append("## Page 1\n\n")
    return "\n\n".join(sections).rstrip() + "\n"


def parse_prose_pdf(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    *,
    repo_root: Path | None = None,
) -> StandardDocument:
    """Parse a non-schematic PDF into Markdown with per-page sections.

    Embedded text is extracted first. Pages with little or no selectable text
    fall back to Tesseract OCR via PyMuPDF (requires a local ``tesseract`` binary).

    Args:
        raw_path: Path to a ``.pdf`` file under ``layout.raw_dir``.
        layout: Data layout configuration for path-derived metadata.
        config: Application configuration (``prose_pdf`` settings).
        repo_root: Optional repository root for ``source_file`` labels.

    Returns:
        Parsed document with normalized Markdown content and metadata.

    Raises:
        ProsePdfParserError: If the file cannot be opened or yields no text.
    """
    base_metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    if base_metadata.document_type == SCHEMATIC_DOCUMENT_TYPE:
        raise ProsePdfParserError(
            f"Prose PDF parser cannot handle sch/ paths: {base_metadata.source_file}"
        )

    if fitz is None:
        raise ProsePdfParserError(
            "pymupdf is required for PDF ingestion: pip install ee-wiki[ml]"
        ) from None

    pdf_cfg = config.prose_pdf
    tessdata_dir = resolve_tessdata_dir(pdf_cfg.tessdata_dir)
    if tessdata_dir is None:
        logger.warning(
            "Prose PDF tessdata not found; OCR for scanned pages will fail. "
            "Install tesseract + language packs, or set ingestion.prose_pdf.tessdata_dir "
            "(macOS Homebrew default: /opt/homebrew/share/tessdata)."
        )
    else:
        logger.info("Prose PDF tessdata: %s", tessdata_dir)

    try:
        document = fitz.open(raw_path)
    except Exception as exc:
        raise ProsePdfParserError(f"Cannot open PDF: {raw_path}") from exc

    page_count = document.page_count
    max_pages = pdf_cfg.max_pages
    limit = page_count if max_pages is None else min(page_count, max_pages)
    if limit <= 0:
        document.close()
        raise ProsePdfParserError(f"PDF has no pages: {raw_path}")

    document_ocr_language = resolve_document_ocr_language(
        document,
        page_limit=limit,
        configured_language=pdf_cfg.ocr_language,
        fallback_language=pdf_cfg.ocr_language_fallback,
        ocr_dpi=pdf_cfg.ocr_dpi,
        tessdata_dir=tessdata_dir,
    )
    resolved_language = (
        document_ocr_language
        if pdf_cfg.ocr_language.casefold() == "auto"
        else pdf_cfg.ocr_language
    )
    logger.info(
        "Prose PDF %s: extracting %d page(s) (ocr_language=%s)",
        raw_path.name,
        limit,
        resolved_language,
    )

    pages: list[PageText] = []
    ocr_pages = 0
    for page_index in range(limit):
        page_num = page_index + 1
        page = document[page_index]
        page_ocr_language = resolve_page_ocr_language(
            page,
            configured_language=pdf_cfg.ocr_language,
            document_language=document_ocr_language,
        )
        try:
            page_text = extract_page_text(
                page,
                page_num=page_num,
                min_text_chars=pdf_cfg.min_text_chars,
                ocr_dpi=pdf_cfg.ocr_dpi,
                ocr_language=page_ocr_language,
                configured_ocr_language=pdf_cfg.ocr_language,
                tessdata_dir=tessdata_dir,
            )
        except Exception as exc:
            document.close()
            raise ProsePdfParserError(
                f"Failed to extract text from {raw_path.name} page {page_num}: {exc}"
            ) from exc
        if page_text.method == "ocr":
            ocr_pages += 1
        pages.append(page_text)
        logger.debug(
            "Prose PDF %s: page %d/%d via %s (%d chars)",
            raw_path.name,
            page_num,
            limit,
            page_text.method,
            len(page_text.text),
        )

    document.close()

    if not any(page.text.strip() for page in pages):
        raise ProsePdfParserError(
            f"No text extracted from PDF: {raw_path}. "
            "Install tesseract for scanned pages (see docs/usage/ingest.md)."
        )

    markdown = _build_markdown(base_metadata.title, pages)
    metadata = replace(base_metadata, page=limit)
    document_out = StandardDocument(
        content=markdown,
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    logger.info(
        "Parsed prose PDF %s (%d pages, %d OCR page(s), %d chars)",
        base_metadata.source_file,
        limit,
        ocr_pages,
        len(markdown),
    )
    return document_out


__all__ = [
    "PDF_SUFFIXES",
    "ProsePdfParserError",
    "parse_prose_pdf",
]
