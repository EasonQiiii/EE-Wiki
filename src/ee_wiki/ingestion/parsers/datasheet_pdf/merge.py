"""Merge per-page extraction results into a single Markdown document."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageResult:
    """Extraction result for a single page."""

    page_num: int
    markdown: str
    ocr_text: str


def merge_pages(title: str, pages: list[PageResult], *, ocr_fidelity: bool = True) -> str:
    """Combine per-page Markdown into a complete document.

    Args:
        title: Document title (from filename).
        pages: Ordered page results.
        ocr_fidelity: When True, append raw OCR text as a searchable appendix.

    Returns:
        Complete Markdown document string.
    """
    sections: list[str] = [f"# {title}\n"]

    for page in pages:
        sections.append(f"## Page {page.page_num + 1}\n")
        if page.markdown.strip():
            sections.append(page.markdown.strip())
        sections.append("")

    if ocr_fidelity:
        ocr_parts: list[str] = []
        for page in pages:
            if page.ocr_text.strip():
                ocr_parts.append(f"### Page {page.page_num + 1} OCR\n")
                ocr_parts.append(page.ocr_text.strip())
                ocr_parts.append("")
        if ocr_parts:
            sections.append("---\n")
            sections.append("## OCR Fidelity Appendix\n")
            sections.extend(ocr_parts)

    return "\n".join(sections) + "\n"
