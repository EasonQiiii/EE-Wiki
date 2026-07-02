"""Extract text from prose PDF pages (embedded text with OCR fallback)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from ee_wiki.common.logging import get_logger

if TYPE_CHECKING:
    import fitz

logger = get_logger(__name__)

ExtractionMethod = Literal["text", "ocr"]


@dataclass(frozen=True)
class PageText:
    """Text extracted from one PDF page."""

    page: int
    text: str
    method: ExtractionMethod


def _normalize_page_text(text: str) -> str:
    """Collapse excessive blank lines while preserving paragraph breaks."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip():
            blank_run = 0
            normalized.append(line)
        else:
            blank_run += 1
            if blank_run <= 1:
                normalized.append("")
    return "\n".join(normalized).strip()


def extract_page_text(
    page: fitz.Page,
    *,
    page_num: int,
    min_text_chars: int,
    ocr_dpi: int,
    ocr_language: str,
    configured_ocr_language: str | None = None,
    tessdata_dir: str | None = None,
) -> PageText:
    """Extract text from a PDF page, using OCR when embedded text is sparse.

    Args:
        page: Open PyMuPDF page handle.
        page_num: 1-based page number for logging.
        min_text_chars: Minimum embedded characters before OCR is attempted.
        ocr_dpi: Render resolution for Tesseract OCR.
        ocr_language: Resolved Tesseract language code for this page.
        configured_ocr_language: Original config value (e.g. ``auto``) for logging.
        tessdata_dir: Directory containing ``*.traineddata`` for PyMuPDF OCR.

    Returns:
        Extracted page text and the method used.
    """
    native = _normalize_page_text(page.get_text("text"))
    if len(native) >= min_text_chars:
        return PageText(page=page_num, text=native, method="text")

    if tessdata_dir is None:
        message = (
            "No tessdata directory found. Install tesseract language packs or set "
            "ingestion.prose_pdf.tessdata_dir (macOS Homebrew: /opt/homebrew/share/tessdata)."
        )
        logger.warning("OCR failed for page %d (native_chars=%d): %s", page_num, len(native), message)
        if native:
            return PageText(page=page_num, text=native, method="text")
        raise RuntimeError(message)

    try:
        logger.debug(
            "Prose PDF page %d: OCR with language=%s tessdata=%s (configured=%s)",
            page_num,
            ocr_language,
            tessdata_dir,
            configured_ocr_language or ocr_language,
        )
        textpage = page.get_textpage_ocr(
            dpi=ocr_dpi,
            full=True,
            language=ocr_language,
            tessdata=tessdata_dir,
        )
        ocr_text = _normalize_page_text(page.get_text("text", textpage=textpage))
    except Exception as exc:
        logger.warning(
            "OCR failed for page %d (native_chars=%d): %s",
            page_num,
            len(native),
            exc,
        )
        if native:
            return PageText(page=page_num, text=native, method="text")
        raise

    if len(ocr_text) >= min_text_chars or len(ocr_text) > len(native):
        logger.info(
            "Prose PDF page %d: OCR extracted %d chars (native had %d)",
            page_num,
            len(ocr_text),
            len(native),
        )
        return PageText(page=page_num, text=ocr_text, method="ocr")

    if native:
        return PageText(page=page_num, text=native, method="text")
    return PageText(page=page_num, text=ocr_text, method="ocr")
