"""Extract, filter, and save embedded raster images from prose PDF pages."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.logging import get_logger

if TYPE_CHECKING:
    import fitz as fitz_mod

logger = get_logger(__name__)


@dataclass(frozen=True)
class ExtractedImage:
    """A single raster image extracted from a PDF page."""

    page: int
    index: int
    png_bytes: bytes
    width: int
    height: int
    content_hash: str
    filename: str


def _image_slug(source_stem: str) -> str:
    """Normalize PDF stem into a filesystem-safe slug for image filenames."""
    import re

    slug = source_stem.lower().replace(" ", "_")
    return re.sub(r"[^\w\-]+", "_", slug).strip("_") or "prose"


def _render_image_to_png(pixmap: object) -> bytes:
    """Convert a PyMuPDF Pixmap to PNG bytes, normalising color space."""
    import fitz

    if not isinstance(pixmap, fitz.Pixmap):
        raise TypeError("Expected fitz.Pixmap")
    if pixmap.alpha:
        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    elif pixmap.n != 3:
        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
    return pixmap.tobytes("png")


def extract_page_images(
    document: fitz_mod.Document,
    page_index: int,
    *,
    min_area: int,
    max_images: int,
) -> list[tuple[bytes, int, int]]:
    """Extract embedded raster images from one PDF page.

    Args:
        document: Open PyMuPDF document.
        page_index: 0-based page index.
        min_area: Minimum pixel area (width * height) to keep.
        max_images: Maximum images to return per page.

    Returns:
        List of (png_bytes, width, height) tuples, largest first.
    """
    import fitz

    page = document[page_index]
    image_list = page.get_images(full=True)
    if not image_list:
        return []

    candidates: list[tuple[bytes, int, int, int]] = []
    for img_info in image_list:
        xref = img_info[0]
        try:
            base_image = document.extract_image(xref)
        except Exception:
            logger.debug("Cannot extract xref %d on page %d", xref, page_index + 1)
            continue
        if base_image is None:
            continue

        width = base_image.get("width", 0)
        height = base_image.get("height", 0)
        area = width * height
        if area < min_area:
            logger.debug(
                "Skipped small image xref=%d on page %d (%dx%d, area=%d < %d)",
                xref, page_index + 1, width, height, area, min_area,
            )
            continue

        img_bytes = base_image.get("image")
        if not img_bytes:
            continue

        ext = base_image.get("ext", "png")
        if ext.lower() != "png":
            try:
                pixmap = fitz.Pixmap(img_bytes)
                png_bytes = _render_image_to_png(pixmap)
            except Exception:
                logger.debug("Failed to convert xref=%d to PNG on page %d", xref, page_index + 1)
                continue
        else:
            png_bytes = img_bytes

        candidates.append((png_bytes, width, height, area))

    candidates.sort(key=lambda c: c[3], reverse=True)
    return [(c[0], c[1], c[2]) for c in candidates[:max_images]]


def _content_hash(data: bytes) -> str:
    """Return a short SHA-256 hex digest for deduplication."""
    return hashlib.sha256(data).hexdigest()[:16]


def extract_and_filter_images(
    document: fitz_mod.Document,
    *,
    page_limit: int,
    source_stem: str,
    min_area: int,
    max_images_per_page: int,
    dedup_max_pages: int,
) -> list[ExtractedImage]:
    """Extract images from all pages, then deduplicate template images.

    Template images (logos, headers) that appear on more than
    ``dedup_max_pages`` different pages are dropped.

    Args:
        document: Open PyMuPDF document.
        page_limit: Number of pages to process.
        source_stem: PDF filename stem for naming output files.
        min_area: Minimum pixel area to keep.
        max_images_per_page: Cap per page.
        dedup_max_pages: Images on more pages than this are dropped.

    Returns:
        Deduplicated list of extracted images.
    """
    slug = _image_slug(source_stem)

    raw_images: list[ExtractedImage] = []
    hash_page_count: Counter[str] = Counter()
    seen_hashes_on_page: dict[int, set[str]] = {}

    for page_index in range(page_limit):
        page_num = page_index + 1
        page_imgs = extract_page_images(
            document,
            page_index,
            min_area=min_area,
            max_images=max_images_per_page,
        )
        seen_hashes_on_page[page_num] = set()
        for img_idx, (png_bytes, w, h) in enumerate(page_imgs):
            h_val = _content_hash(png_bytes)
            filename = f"{slug}_p{page_num}_img{img_idx}.png"
            raw_images.append(ExtractedImage(
                page=page_num,
                index=img_idx,
                png_bytes=png_bytes,
                width=w,
                height=h,
                content_hash=h_val,
                filename=filename,
            ))
            if h_val not in seen_hashes_on_page[page_num]:
                seen_hashes_on_page[page_num].add(h_val)
                hash_page_count[h_val] += 1

    template_hashes = {h for h, count in hash_page_count.items() if count > dedup_max_pages}
    if template_hashes:
        logger.info(
            "Dropping %d template image hash(es) appearing on >%d pages",
            len(template_hashes),
            dedup_max_pages,
        )

    seen_hashes: set[str] = set()
    result: list[ExtractedImage] = []
    for img in raw_images:
        if img.content_hash in template_hashes:
            continue
        if img.content_hash in seen_hashes:
            continue
        seen_hashes.add(img.content_hash)
        result.append(img)

    logger.info(
        "Extracted %d unique images from %d pages (raw=%d, templates=%d)",
        len(result),
        page_limit,
        len(raw_images),
        len(template_hashes),
    )
    return result


def save_images(
    images: list[ExtractedImage],
    images_dir: Path,
) -> None:
    """Write extracted images to disk.

    Args:
        images: Images to save.
        images_dir: Target directory (created if needed).
    """
    if not images:
        return
    images_dir.mkdir(parents=True, exist_ok=True)
    for img in images:
        path = images_dir / img.filename
        path.write_bytes(img.png_bytes)
    logger.info("Saved %d images to %s", len(images), images_dir)
