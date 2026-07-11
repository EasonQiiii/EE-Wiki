"""Extract Figure/Table labels from datasheet OCR text and enrich VLM markdown."""

from __future__ import annotations

import re

_LABEL_LINE = re.compile(r"^(Figure|Table)\s+(\d+)\.\s*$", re.IGNORECASE)
_NEXT_LABEL = re.compile(r"^(Figure|Table)\s+\d+\.", re.IGNORECASE)


def extract_ocr_label_headings(ocr_text: str) -> list[tuple[str, str]]:
    """Parse PDF text layer for Figure/Table labels and optional titles.

    Args:
        ocr_text: Raw PyMuPDF text for one page.

    Returns:
        Ordered ``(label, title)`` pairs, e.g. ``("Figure 58", "Synchronous …")``.
    """
    lines = [line.strip() for line in ocr_text.splitlines()]
    results: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        match = _LABEL_LINE.match(lines[index])
        if not match:
            index += 1
            continue
        kind = match.group(1).title()
        number = match.group(2)
        label = f"{kind} {number}"
        title = ""
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor]:
            cursor += 1
        if cursor < len(lines) and not _NEXT_LABEL.match(lines[cursor]):
            title = lines[cursor].strip()
        results.append((label, title))
        index += 1
    return results


def enrich_page_markdown_with_labels(markdown: str, ocr_text: str) -> str:
    """Prepend ``### Figure N. title`` headings from OCR when VLM output omitted them.

    Args:
        markdown: VLM or text extraction body for the page.
        ocr_text: Raw OCR text for the same page.

    Returns:
        Markdown with label headings inserted when missing.
    """
    body = markdown.strip()
    if not ocr_text.strip():
        return body

    collapsed = body.replace(" ", "").casefold()
    additions: list[str] = []
    for label, title in extract_ocr_label_headings(ocr_text):
        needle = label.replace(" ", "").casefold()
        if needle in collapsed:
            continue
        if title:
            additions.append(f"### {label}. {title}")
        else:
            additions.append(f"### {label}.")

    if not additions:
        return body
    return "\n\n".join(additions) + "\n\n" + body
