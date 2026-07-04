"""Parse schematic PDF files into Markdown and schematic metadata."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.common.types import DataLayoutConfig, StandardDocument
from ee_wiki.ingestion.parsers.pdf_common import PDF_SUFFIXES
from ee_wiki.ingestion.parsers.schematic_pdf.engine import (
    SchematicVisionEngine,
    build_vision_engine,
)
from ee_wiki.ingestion.parsers.schematic_pdf.fallback import build_fallback_report
from ee_wiki.ingestion.parsers.schematic_pdf.layout import (
    PageLayoutResult,
    SchematicLayoutEngine,
    build_layout_engine,
)
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction, merge_page_extractions
from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import (
    build_fidelity_extraction,
    enrich_with_fidelity,
)
from ee_wiki.ingestion.parsers.schematic_pdf.prompt import schematic_image_slug
from ee_wiki.ingestion.path_metadata import parse_path_metadata
from ee_wiki.knowledge.store.processed import resolve_processed_paths

try:
    import fitz
except ImportError:  # pragma: no cover - optional at import time
    fitz = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:
    from ee_wiki.common.config import AppConfig

logger = get_logger(__name__)


class SchematicPdfParserError(EEWikiError):
    """Failed to parse a schematic PDF."""


def _project_id(metadata_title: str, raw_path: Path) -> str:
    return metadata_title or raw_path.stem


def _images_dir(raw_path: Path, layout: DataLayoutConfig) -> Path:
    content_path, _ = resolve_processed_paths(
        raw_path,
        layout,
        content_extension=".md",
    )
    slug = schematic_image_slug(raw_path.stem)
    return content_path.parent / "images" / slug


def parse_schematic_pdf(
    raw_path: Path,
    layout: DataLayoutConfig,
    config: AppConfig,
    *,
    repo_root: Path | None = None,
    vision_engine: SchematicVisionEngine | None = None,
    layout_engine: SchematicLayoutEngine | None = None,
) -> StandardDocument:
    """Parse a schematic PDF under ``sch/`` into Markdown and metadata.

    Pipeline (ported from legacy temp3.py):
      PDF page → LayoutLMv3 figure crop + OCR text
      → Qwen3-VL Markdown reconstruction (crop + OCR prompt)
      → rule-based fallback when VLM fails
    """
    base_metadata = parse_path_metadata(raw_path, layout, repo_root=repo_root)
    if base_metadata.document_type != SCHEMATIC_DOCUMENT_TYPE:
        raise SchematicPdfParserError(
            f"PDF schematic parser requires sch/ path, got: {base_metadata.source_file}"
        )

    if fitz is None:
        raise SchematicPdfParserError(
            "pymupdf is required for PDF ingestion: pip install ee-wiki[ml]"
        ) from None

    try:
        document = fitz.open(raw_path)
    except Exception as exc:
        raise SchematicPdfParserError(f"Cannot open PDF: {raw_path}") from exc

    page_count = document.page_count
    max_pages = config.schematic_pdf.max_pages
    limit = page_count if max_pages is None else min(page_count, max_pages)
    if limit <= 0:
        document.close()
        raise SchematicPdfParserError(f"PDF has no pages: {raw_path}")

    layout_engine = layout_engine or build_layout_engine(config)
    images_dir = _images_dir(raw_path, layout)
    project_id = _project_id(base_metadata.title, raw_path)
    images_rel_prefix = config.schematic_pdf.images_rel_prefix
    fidelity_mode = config.schematic_pdf.fidelity_mode
    use_vlm = fidelity_mode != "ocr_only"
    if use_vlm and vision_engine is None:
        vision_engine = build_vision_engine(config)

    logger.info(
        "Schematic PDF %s: pipeline for %d page(s) (fidelity_mode=%s)",
        raw_path.name,
        limit,
        fidelity_mode,
    )

    extractions: list[PageExtraction] = []
    for page_index in range(limit):
        page_num = page_index + 1
        if fidelity_mode == "ocr_only":
            logger.info(
                "Schematic PDF %s: page %d/%d — OCR fidelity",
                raw_path.name,
                page_num,
                limit,
            )
            raw_ocr_text = document[page_index].get_text()
            page_layout = PageLayoutResult(
                page=page_num,
                raw_ocr_text=raw_ocr_text,
                crop_image_bytes=None,
                slice_filenames=[],
            )
            extractions.append(
                build_fidelity_extraction(page_layout, project_id=project_id)
            )
            continue

        logger.info("Schematic PDF %s: page %d/%d — layout analysis", raw_path.name, page_num, limit)
        page_layout = layout_engine.analyze_page(
            raw_path,
            page_index,
            images_dir=images_dir,
            source_stem=raw_path.stem,
            save_page_images=config.schematic_pdf.save_page_images,
        )

        logger.info("Schematic PDF %s: page %d/%d — VLM reconstruction", raw_path.name, page_num, limit)
        extraction = vision_engine.extract_page(
            page_layout, project_id=project_id, source_stem=raw_path.stem,
        )
        if extraction is None:
            logger.warning(
                "VLM failed for %s page %d, using rule-based fallback",
                raw_path.name,
                page_num,
            )
            extraction = build_fallback_report(
                page_layout,
                project_id=project_id,
                source_stem=raw_path.stem,
                images_rel_prefix=images_rel_prefix,
            )
        if fidelity_mode == "vlm_plus_ocr":
            extraction = enrich_with_fidelity(extraction, page_layout)
        extractions.append(extraction)

    document.close()

    markdown, components, nets, interfaces = merge_page_extractions(
        extractions,
        title=base_metadata.title,
    )

    metadata = replace(
        base_metadata,
        page=limit,
        major_components=components,
        nets=nets,
        interfaces=interfaces,
    )
    document_out = StandardDocument(
        content=markdown,
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    logger.info(
        "Parsed schematic PDF %s (%d pages, %d components, %d nets)",
        base_metadata.source_file,
        limit,
        len(components),
        len(nets),
    )
    return document_out


__all__ = [
    "PDF_SUFFIXES",
    "SchematicPdfParserError",
    "parse_schematic_pdf",
]
