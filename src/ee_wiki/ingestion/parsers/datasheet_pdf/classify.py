"""Page classification for datasheet PDFs.

Determines whether each page is primarily text, a table, a graph/chart,
or a mix requiring full VLM processing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import fitz


class PageType(Enum):
    """Classification of a single datasheet page."""

    TEXT = "text"
    TABLE = "table"
    GRAPH = "graph"
    MIXED = "mixed"


@dataclass(frozen=True)
class PageClassification:
    """Result of classifying a single page."""

    page_num: int
    page_type: PageType
    text_chars: int
    vector_line_count: int
    image_area_ratio: float


def _count_vector_lines(page: fitz.Page) -> int:
    """Count horizontal/vertical line-drawing operations on a page.

    Table-heavy pages have many short lines forming grid borders.
    """
    drawings = page.get_drawings()
    line_count = 0
    for item in drawings:
        for cmd in item.get("items", []):
            if cmd[0] in ("l", "re"):
                line_count += 1
    return line_count


def _image_area_ratio(page: fitz.Page) -> float:
    """Fraction of the page area covered by raster images."""
    page_rect = page.rect
    page_area = page_rect.width * page_rect.height
    if page_area <= 0:
        return 0.0

    image_area = 0.0
    for img_info in page.get_image_info():
        bbox = img_info.get("bbox")
        if bbox:
            w = abs(bbox[2] - bbox[0])
            h = abs(bbox[3] - bbox[1])
            image_area += w * h

    return min(image_area / page_area, 1.0)


def classify_page(
    page: fitz.Page,
    page_num: int,
    *,
    min_text_chars_for_skip: int = 500,
    vector_line_threshold: int = 50,
    image_area_threshold: float = 0.6,
) -> PageClassification:
    """Classify a single PDF page by content type.

    Args:
        page: PyMuPDF page object.
        page_num: 0-based page index.
        min_text_chars_for_skip: Text-only threshold (no VLM needed).
        vector_line_threshold: Above this → likely a table page.
        image_area_threshold: Above this → likely a graph/chart page.

    Returns:
        Classification result with metrics.
    """
    text = page.get_text("text") or ""
    text_chars = len(text.strip())
    vector_lines = _count_vector_lines(page)
    img_ratio = _image_area_ratio(page)

    if vector_lines >= vector_line_threshold:
        page_type = PageType.TABLE
    elif img_ratio >= image_area_threshold and text_chars < 200:
        page_type = PageType.GRAPH
    elif text_chars >= min_text_chars_for_skip and vector_lines < 20:
        page_type = PageType.TEXT
    else:
        page_type = PageType.MIXED

    return PageClassification(
        page_num=page_num,
        page_type=page_type,
        text_chars=text_chars,
        vector_line_count=vector_lines,
        image_area_ratio=img_ratio,
    )
