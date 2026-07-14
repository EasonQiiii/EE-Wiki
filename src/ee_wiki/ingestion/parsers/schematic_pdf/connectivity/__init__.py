"""Schematic connectivity extraction: CAD-first, PDF geometry fallback."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.cad_companion import (
    discover_cad_companions,
    try_parse_cad_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    ConnectorBinding,
    PageConnectivity,
    SchematicConnectivity,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.pdf_geometry import (
    extract_page_connectivity_from_geometry,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.resolve import (
    resolve_page_module_nets,
)

__all__ = [
    "ConnectorBinding",
    "PageConnectivity",
    "SchematicConnectivity",
    "discover_cad_companions",
    "extract_page_connectivity_from_geometry",
    "resolve_page_module_nets",
    "try_parse_cad_module_nets",
]
