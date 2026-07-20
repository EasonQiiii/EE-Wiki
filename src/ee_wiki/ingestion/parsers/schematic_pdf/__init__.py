"""Parse schematic PDF files into Markdown and schematic metadata."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.common.types import DataLayoutConfig, PageMetadata, StandardDocument
from ee_wiki.ingestion.parsers.pdf_common import PDF_SUFFIXES
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.discover import (
    ParsedCompanions,
    discover_and_parse_companions,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.merge import (
    merge_connectivity,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionManifest,
    PageConnectivity,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.resolve import (
    resolve_page_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.engine import (
    SchematicVisionEngine,
    build_vision_engine,
)
from ee_wiki.ingestion.parsers.schematic_pdf.fallback import build_fallback_report
from ee_wiki.ingestion.parsers.schematic_pdf.layout import (
    PageLayoutResult,
    SchematicLayoutEngine,
    build_layout_engine,
    extract_page_ocr_tokens,
)
from ee_wiki.ingestion.parsers.schematic_pdf.merge import PageExtraction, merge_page_extractions
from ee_wiki.ingestion.parsers.schematic_pdf.ocr_fidelity import (
    build_fidelity_extraction,
    enrich_with_fidelity,
    extract_fidelity_fields,
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


def _connectivity_kwargs(config: AppConfig) -> dict:
    conn = config.schematic_pdf.connectivity
    return {
        "connectivity_enabled": conn.enabled,
        "max_connector_distance": conn.max_connector_distance,
        "cad_extensions": conn.netlist_extensions or conn.cad_extensions,
    }


def _append_page_connectivity(
    pages: list[PageConnectivity],
    layout: PageLayoutResult,
    *,
    config: AppConfig,
) -> None:
    """Resolve and record page-level PDF/OCR connectivity when enabled."""
    conn = config.schematic_pdf.connectivity
    if not conn.enabled:
        return
    fields = extract_fidelity_fields(layout.raw_ocr_text)
    _module_nets, _source, page_conn = resolve_page_module_nets(
        page=layout.page,
        module_labels=fields.module_labels,
        nets=fields.nets,
        ocr_text=layout.raw_ocr_text,
        ocr_tokens=layout.ocr_tokens or None,
        pdf_path=layout.source_pdf,
        cad_extensions=conn.netlist_extensions or conn.cad_extensions,
        max_connector_distance=conn.max_connector_distance,
        skip_cad_discovery=True,
    )
    if page_conn is not None:
        pages.append(page_conn)


def _write_connectivity_sidecar(
    raw_path: Path,
    layout: DataLayoutConfig,
    connectivity: object,
) -> Path | None:
    """Write ``*.connectivity.json`` next to the processed Markdown mirror."""
    content_path, _ = resolve_processed_paths(
        raw_path,
        layout,
        content_extension=".md",
    )
    sidecar_path = content_path.with_name(f"{content_path.stem}.connectivity.json")
    try:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        payload = connectivity.to_dict()  # type: ignore[attr-defined]
        sidecar_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Failed to write connectivity sidecar %s: %s", sidecar_path, exc)
        return None
    logger.info("Wrote schematic connectivity sidecar %s", sidecar_path)
    return sidecar_path


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
      → ADR 0009 multi-source map (netlist + boardview + PDF geometry + OCR)
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
    conn_kwargs = _connectivity_kwargs(config)
    connectivity_pages: list[PageConnectivity] = []
    conn_cfg = config.schematic_pdf.connectivity
    parsed_companions: ParsedCompanions | None = None
    if conn_cfg.enabled:
        parsed_companions = discover_and_parse_companions(
            raw_path,
            netlist_extensions=conn_cfg.netlist_extensions or conn_cfg.cad_extensions,
            boardview_extensions=conn_cfg.boardview_extensions,
        )

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
                ocr_tokens=extract_page_ocr_tokens(document[page_index]),
                source_pdf=raw_path,
            )
            extractions.append(
                build_fidelity_extraction(
                    page_layout,
                    project_id=project_id,
                    **conn_kwargs,
                )
            )
            _append_page_connectivity(connectivity_pages, page_layout, config=config)
            continue

        logger.info(
            "Schematic PDF %s: page %d/%d — layout analysis",
            raw_path.name,
            page_num,
            limit,
        )
        page_layout = layout_engine.analyze_page(
            raw_path,
            page_index,
            images_dir=images_dir,
            source_stem=raw_path.stem,
            save_page_images=config.schematic_pdf.save_page_images,
        )

        logger.info(
            "Schematic PDF %s: page %d/%d — VLM reconstruction",
            raw_path.name,
            page_num,
            limit,
        )
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
                **conn_kwargs,
            )
        if fidelity_mode == "vlm_plus_ocr":
            extraction = enrich_with_fidelity(extraction, page_layout, **conn_kwargs)
        extractions.append(extraction)
        _append_page_connectivity(connectivity_pages, page_layout, config=config)

    document.close()

    markdown, components, nets, interfaces = merge_page_extractions(
        extractions,
        title=base_metadata.title,
    )

    page_metadata = [
        PageMetadata(
            page=extraction.page,
            major_components=list(extraction.major_components),
            nets=list(extraction.nets),
            interfaces=list(extraction.interfaces),
        )
        for extraction in sorted(extractions, key=lambda item: item.page)
    ]

    metadata = replace(
        base_metadata,
        page=limit,
        major_components=components,
        nets=nets,
        interfaces=interfaces,
        pages=page_metadata,
    )
    document_out = StandardDocument(
        content=markdown,
        metadata=metadata,
        source_ref=str(raw_path.resolve()),
    )
    if conn_cfg.enabled and conn_cfg.write_sidecar:
        sidecar = merge_connectivity(
            source_file=base_metadata.source_file,
            companions=parsed_companions
            or ParsedCompanions(manifest=CompanionManifest()),
            pages=connectivity_pages,
        )
        _write_connectivity_sidecar(raw_path, layout, sidecar)
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
