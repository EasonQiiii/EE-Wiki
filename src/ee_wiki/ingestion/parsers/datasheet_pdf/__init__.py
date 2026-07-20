"""Datasheet PDF parser — VLM-based page-level extraction.

Routes each page to the appropriate extraction strategy based on content
classification (text-only, table, graph, mixed). Text-heavy pages use fast
PyMuPDF text extraction; table and graph pages use Qwen3-VL for structured
Markdown output.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import fitz

from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.parsers.datasheet_pdf.classify import (
    PageType,
    classify_page,
)
from ee_wiki.ingestion.parsers.datasheet_pdf.engine import (
    DatasheetVisionEngine,
    build_datasheet_engine,
)
from ee_wiki.ingestion.parsers.datasheet_pdf.fields import extract_datasheet_fields
from ee_wiki.ingestion.parsers.datasheet_pdf.merge import PageResult, merge_pages
from ee_wiki.ingestion.parsers.datasheet_pdf.quality import (
    VlmQualityThresholds,
    select_page_markdown,
)
from ee_wiki.ingestion.path_metadata import parse_path_metadata

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig, DataLayoutConfig

logger = get_logger(__name__)


def _render_page_png(page: fitz.Page, *, dpi: int = 200) -> bytes:
    """Render a single PDF page to PNG bytes."""
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def _save_page_image(
    page_bytes: bytes,
    *,
    output_dir: Path,
    stem: str,
    page_num: int,
    images_rel_prefix: str,
) -> str:
    """Save a page render and return relative path for Markdown references."""
    images_dir = output_dir / images_rel_prefix / stem
    images_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{stem}_p{page_num + 1}_page.png"
    (images_dir / filename).write_bytes(page_bytes)
    return f"{images_rel_prefix}/{stem}/{filename}"


def parse_datasheet_pdf(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    *,
    repo_root: Path | None = None,
    engine: DatasheetVisionEngine | None = None,
) -> StandardDocument:
    """Parse a datasheet PDF using page classification + VLM extraction.

    Args:
        raw_path: Path to the raw PDF under ``data/raw/``.
        layout: Data layout configuration.
        config: Full application configuration.
        repo_root: Repository root (inferred if not provided).
        engine: Optional pre-built VLM engine (for reuse across files).

    Returns:
        StandardDocument with structured Markdown content.

    Raises:
        DatasheetVisionError: If VLM model cannot be loaded.
    """
    metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    ds_cfg = config.datasheet_pdf
    stem = raw_path.stem

    doc = fitz.open(raw_path)
    total_pages = len(doc)
    if ds_cfg.max_pages is not None:
        total_pages = min(total_pages, ds_cfg.max_pages)

    logger.info(
        "Datasheet ingest: %s (%d pages, max_pages=%s)",
        raw_path.name,
        total_pages,
        ds_cfg.max_pages,
    )

    # Classify all pages first
    classifications = []
    for i in range(total_pages):
        page = doc[i]
        clf = classify_page(
            page,
            i,
            min_text_chars_for_skip=ds_cfg.min_text_chars_for_skip,
            vector_line_threshold=ds_cfg.vector_line_threshold,
            image_area_threshold=ds_cfg.image_area_threshold,
        )
        classifications.append(clf)
        logger.debug(
            "Page %d classified as %s (text=%d, vectors=%d, img_ratio=%.2f)",
            i + 1,
            clf.page_type.value,
            clf.text_chars,
            clf.vector_line_count,
            clf.image_area_ratio,
        )

    vlm_pages = [c for c in classifications if c.page_type != PageType.TEXT]
    needs_vlm = len(vlm_pages) > 0
    logger.info(
        "Page classification: %d text, %d table, %d graph, %d mixed → VLM needed: %s",
        sum(1 for c in classifications if c.page_type == PageType.TEXT),
        sum(1 for c in classifications if c.page_type == PageType.TABLE),
        sum(1 for c in classifications if c.page_type == PageType.GRAPH),
        sum(1 for c in classifications if c.page_type == PageType.MIXED),
        needs_vlm,
    )

    # Lazily build VLM engine only if needed
    vlm: DatasheetVisionEngine | None = engine
    if needs_vlm and vlm is None:
        vlm = build_datasheet_engine(config)

    # Determine output directory for page images
    target_rel = raw_path.relative_to(layout.raw_dir)
    output_dir = layout.processed_dir / target_rel.parent

    # Process each page
    page_results: list[PageResult] = []
    for clf in classifications:
        page = doc[clf.page_num]
        ocr_text = (page.get_text("text") or "").strip()

        if clf.page_type == PageType.TEXT:
            page_results.append(PageResult(
                page_num=clf.page_num,
                markdown=ocr_text,
                ocr_text=ocr_text,
            ))
        else:
            page_png = _render_page_png(page)

            if ds_cfg.save_page_images:
                _save_page_image(
                    page_png,
                    output_dir=output_dir,
                    stem=stem,
                    page_num=clf.page_num,
                    images_rel_prefix=ds_cfg.images_rel_prefix,
                )

            assert vlm is not None
            vlm_markdown = vlm.extract_page(
                page_png,
                clf.page_num,
                clf.page_type,
                ocr_text=ocr_text if ocr_text else None,
            )
            thresholds = VlmQualityThresholds(
                enabled=ds_cfg.vlm_quality_gate,
                max_empty_cell_ratio=ds_cfg.vlm_max_empty_cell_ratio,
                min_length_ratio=ds_cfg.vlm_min_length_ratio,
                max_garble_ratio=ds_cfg.vlm_max_garble_ratio,
                min_ocr_chars=ds_cfg.vlm_min_ocr_chars_for_fallback,
                min_table_rows_vs_ocr_lines=ds_cfg.vlm_min_table_rows_vs_ocr_lines,
            )
            page_markdown, _score = select_page_markdown(
                vlm_markdown=vlm_markdown,
                ocr_text=ocr_text,
                page_type=clf.page_type,
                page_num=clf.page_num,
                thresholds=thresholds,
            )

            page_results.append(PageResult(
                page_num=clf.page_num,
                markdown=page_markdown,
                ocr_text=ocr_text,
            ))

    doc.close()

    content = merge_pages(
        title=stem,
        pages=page_results,
        ocr_fidelity=ds_cfg.ocr_fidelity,
    )

    ds_fields = extract_datasheet_fields(content)

    stat = raw_path.stat()
    final_metadata = Metadata(
        product=metadata.product,
        project=metadata.project,
        build=metadata.build,
        document_type=metadata.document_type,
        title=stem,
        source_file=str(raw_path),
        target_file=str(layout.processed_dir / target_rel.with_suffix(".md")),
        source_mtime=stat.st_mtime,
        source_size=stat.st_size,
        supply_voltage=ds_fields.supply_voltage or None,
        pin_count=ds_fields.pin_count,
        package=ds_fields.package,
        interfaces=ds_fields.interfaces or None,
    )

    return StandardDocument(
        content=content,
        metadata=final_metadata,
        source_ref=str(raw_path),
    )
