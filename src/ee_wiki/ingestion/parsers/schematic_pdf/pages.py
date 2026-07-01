"""Render schematic PDF pages to images for vision parsing."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger

logger = get_logger(__name__)


class PdfRenderError(EEWikiError):
    """Failed to render a PDF page."""


def render_pdf_pages(
    pdf_path: Path,
    *,
    dpi: int = 200,
    max_pages: int | None = None,
) -> list[tuple[int, bytes]]:
    """Render PDF pages to PNG bytes.

    Args:
        pdf_path: Path to the source PDF.
        dpi: Render resolution.
        max_pages: Optional cap on pages to render.

    Returns:
        List of ``(page_number, png_bytes)`` tuples (1-based page numbers).

    Raises:
        PdfRenderError: If the PDF cannot be opened or rendered.
    """
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise PdfRenderError(
            "pymupdf is required for PDF ingestion: pip install ee-wiki[ml]"
        ) from exc

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise PdfRenderError(f"Cannot open PDF: {pdf_path}") from exc

    pages: list[tuple[int, bytes]] = []
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    page_count = document.page_count
    limit = page_count if max_pages is None else min(page_count, max_pages)

    for index in range(limit):
        page = document.load_page(index)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        png_bytes = pixmap.tobytes("png")
        pages.append((index + 1, png_bytes))

    document.close()
    logger.info("Rendered %d page(s) from %s at %d DPI", len(pages), pdf_path.name, dpi)
    return pages
