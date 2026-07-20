"""Resolve module→nets using PDF geometry → OCR spatial (page-level).

Document-level netlist/boardview companions are parsed once via
:mod:`discover` and merged in :mod:`merge` (ADR 0009). Optional
``companion_module_nets`` may still enrich a page when callers pass them.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.cad_companion import (
    discover_cad_companions,
    try_parse_cad_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    ConnectivitySource,
    PageConnectivity,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.pdf_geometry import (
    extract_page_connectivity_from_geometry,
)
from ee_wiki.ingestion.parsers.schematic_pdf.signals import (
    OcrToken,
    associate_nets_to_modules,
)

logger = get_logger(__name__)


def resolve_page_module_nets(
    *,
    page: int,
    module_labels: Sequence[str],
    nets: Sequence[str],
    ocr_text: str,
    ocr_tokens: Sequence[OcrToken] | None,
    pdf_path: Path | None = None,
    cad_extensions: tuple[str, ...] | None = None,
    max_connector_distance: float = 90.0,
    prefer_geometry: bool = True,
    companion_module_nets: dict[str, list[str]] | None = None,
    skip_cad_discovery: bool = False,
) -> tuple[dict[str, list[str]], ConnectivitySource, PageConnectivity | None]:
    """Resolve module→net map for one schematic page.

    Evidence order for **page** bindings (ADR 0007 / 0009):

    1. Optional pre-parsed ``companion_module_nets`` (``cad_netlist``)
    2. Legacy on-demand CAD discovery when ``skip_cad_discovery`` is False
    3. PDF connector geometry
    4. OCR spatial

    Args:
        page: 1-based page number.
        module_labels: Zone titles from OCR.
        nets: Page net names.
        ocr_text: Raw OCR text (spatial fallback).
        ocr_tokens: Optional word boxes.
        pdf_path: Raw schematic PDF path for optional legacy CAD discovery.
        cad_extensions: Optional CAD suffixes from config.
        max_connector_distance: Geometry catchment radius.
        prefer_geometry: When True, try PDF connector catchment before OCR spatial.
        companion_module_nets: Pre-parsed module→nets from document-level companions.
        skip_cad_discovery: When True, do not re-discover companions per page.

    Returns:
        Tuple of ``(module_nets, source, page_connectivity_or_none)``.
    """
    if companion_module_nets:
        logger.info("Page %d connectivity source=cad_netlist (pre-parsed)", page)
        connectivity = PageConnectivity(
            page=page,
            source="cad_netlist",
            module_nets=dict(companion_module_nets),
        )
        return dict(companion_module_nets), "cad_netlist", connectivity

    if not skip_cad_discovery and pdf_path is not None:
        companions = discover_cad_companions(pdf_path, extensions=cad_extensions)
        cad_nets = try_parse_cad_module_nets(companions)
        if cad_nets:
            logger.info("Page %d connectivity source=cad_netlist", page)
            connectivity = PageConnectivity(
                page=page,
                source="cad_netlist",
                module_nets=cad_nets,
            )
            return cad_nets, "cad_netlist", connectivity

    if prefer_geometry and ocr_tokens:
        geometry = extract_page_connectivity_from_geometry(
            page=page,
            module_labels=module_labels,
            nets=nets,
            ocr_tokens=ocr_tokens,
            max_connector_distance=max_connector_distance,
        )
        if geometry is not None and geometry.module_nets:
            spatial = associate_nets_to_modules(
                module_labels,
                nets,
                ocr_text=ocr_text,
                ocr_tokens=ocr_tokens,
            )
            merged = dict(spatial)
            for label, label_nets in geometry.module_nets.items():
                merged[label] = label_nets
            logger.info(
                "Page %d connectivity source=pdf_geometry connectors=%d modules=%d",
                page,
                len(geometry.connectors),
                len(geometry.module_nets),
            )
            return merged, "pdf_geometry", geometry

    spatial = associate_nets_to_modules(
        module_labels,
        nets,
        ocr_text=ocr_text,
        ocr_tokens=ocr_tokens,
    )
    connectivity = PageConnectivity(
        page=page,
        source="ocr_spatial",
        module_nets=dict(spatial),
    )
    return spatial, "ocr_spatial", connectivity
