"""Schematic connectivity: multi-source map (ADR 0007 / 0009)."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.cad_companion import (
    discover_cad_companions,
    try_parse_cad_module_nets,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.discover import (
    DiscoveredCompanions,
    ParsedCompanions,
    discover_and_parse_companions,
    discover_companions,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.merge import merge_connectivity
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionGraph,
    CompanionManifest,
    ConnectorBinding,
    PageConnectivity,
    PinNetBinding,
    SchematicConnectivity,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.pdf_geometry import (
    extract_page_connectivity_from_geometry,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.resolve import (
    resolve_page_module_nets,
)

__all__ = [
    "CompanionGraph",
    "CompanionManifest",
    "ConnectorBinding",
    "DiscoveredCompanions",
    "PageConnectivity",
    "ParsedCompanions",
    "PinNetBinding",
    "SchematicConnectivity",
    "discover_and_parse_companions",
    "discover_cad_companions",
    "discover_companions",
    "extract_page_connectivity_from_geometry",
    "merge_connectivity",
    "resolve_page_module_nets",
    "try_parse_cad_module_nets",
]
