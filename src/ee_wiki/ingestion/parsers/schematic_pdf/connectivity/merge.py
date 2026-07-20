"""Merge netlist, boardview, and page-level PDF/OCR connectivity (ADR 0009)."""

from __future__ import annotations

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.discover import ParsedCompanions
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    EVIDENCE_PRIORITY,
    CompanionGraph,
    CompanionManifest,
    ConnectivitySource,
    PageConnectivity,
    PinNetBinding,
    SchematicConnectivity,
)

logger = get_logger(__name__)


def _merge_bindings(
    *graphs: CompanionGraph | None,
) -> list[PinNetBinding]:
    """Merge pin–net bindings; higher evidence priority wins on (refdes, pin)."""
    winners: dict[tuple[str, str], PinNetBinding] = {}
    # Process lowest priority first so higher can overwrite.
    ordered: list[CompanionGraph] = [g for g in graphs if g is not None]
    ordered.sort(key=lambda g: EVIDENCE_PRIORITY.get(g.evidence, 0))
    for graph in ordered:
        for binding in graph.bindings:
            key = (binding.refdes, binding.pin)
            existing = winners.get(key)
            if existing is None:
                winners[key] = binding
                continue
            if EVIDENCE_PRIORITY.get(binding.evidence, 0) >= EVIDENCE_PRIORITY.get(
                existing.evidence, 0
            ):
                winners[key] = binding
    return list(winners.values())


def _index_bindings(
    bindings: list[PinNetBinding],
) -> tuple[dict[str, list[PinNetBinding]], dict[str, list[PinNetBinding]]]:
    nets: dict[str, list[PinNetBinding]] = {}
    parts: dict[str, list[PinNetBinding]] = {}
    for binding in bindings:
        nets.setdefault(binding.net, []).append(binding)
        parts.setdefault(binding.refdes, []).append(binding)
    for net in nets:
        nets[net] = sorted(nets[net], key=lambda b: (b.refdes, b.pin))
    for refdes in parts:
        parts[refdes] = sorted(parts[refdes], key=lambda b: (b.pin, b.net))
    return nets, parts


def merge_connectivity(
    *,
    source_file: str,
    companions: ParsedCompanions | None,
    pages: list[PageConnectivity],
) -> SchematicConnectivity:
    """Build a schema-v2 :class:`SchematicConnectivity` from all sources.

    Args:
        source_file: Schematic PDF source path string for the sidecar.
        companions: Parsed netlist/boardview (may be absent).
        pages: Per-page PDF geometry / OCR results.

    Returns:
        Document-level connectivity ready for ``*.connectivity.json``.
    """
    parsed = companions or ParsedCompanions(manifest=CompanionManifest())
    bindings = _merge_bindings(parsed.netlist, parsed.boardview)
    nets, parts = _index_bindings(bindings)

    sources_used: list[ConnectivitySource] = []
    if parsed.netlist is not None and parsed.netlist.bindings:
        sources_used.append("cad_netlist")
    if parsed.boardview is not None and parsed.boardview.bindings:
        sources_used.append("boardview")
    page_sources = {page.source for page in pages}
    for tag in ("pdf_geometry", "ocr_spatial"):
        if tag in page_sources:
            sources_used.append(tag)  # type: ignore[arg-type]

    logger.info(
        "Merged connectivity for %s: sources_used=%s nets=%d parts=%d pages=%d",
        source_file,
        sources_used,
        len(nets),
        len(parts),
        len(pages),
    )
    return SchematicConnectivity(
        source_file=source_file,
        pages=list(pages),
        companions=parsed.manifest,
        sources_used=sources_used,
        nets=nets,
        parts=parts,
    )
