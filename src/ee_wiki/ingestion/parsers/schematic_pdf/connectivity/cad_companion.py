"""Backward-compatible CAD companion discovery entry points.

New code should prefer :mod:`discover` and :mod:`registry` (ADR 0009).
"""

from __future__ import annotations

from pathlib import Path

from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.discover import (
    DEFAULT_NETLIST_EXTENSIONS,
    discover_companions,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import CompanionGraph
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.registry import (
    parse_companion_file,
)

# Re-export historical default (netlist only; boardview is separate in ADR 0009).
DEFAULT_CAD_EXTENSIONS: tuple[str, ...] = DEFAULT_NETLIST_EXTENSIONS


def discover_cad_companions(
    pdf_path: Path,
    *,
    extensions: tuple[str, ...] | None = None,
) -> list[Path]:
    """Return candidate CAD/netlist paths for ``pdf_path`` (legacy API).

    Does not include boardview ``.brd`` unless ``extensions`` lists it.

    Args:
        pdf_path: Path to the schematic PDF under ``data/raw/``.
        extensions: File suffixes to accept (including the leading dot).

    Returns:
        Deduplicated existing paths in preference order.
    """
    discovered = discover_companions(
        pdf_path,
        netlist_extensions=extensions
        if extensions is not None
        else DEFAULT_NETLIST_EXTENSIONS,
        boardview_extensions=(),
    )
    return list(discovered.netlist_paths)


def try_parse_cad_module_nets(
    companions: list[Path],
) -> dict[str, list[str]] | None:
    """Best-effort parse of companion CAD/netlist into module→nets.

    Prefer document-level :func:`discover.discover_and_parse_companions`.
    This legacy helper groups nets by refdes when a pin–net graph is available.

    Args:
        companions: Preferred-order CAD paths from :func:`discover_cad_companions`.

    Returns:
        Module/refdes → net names when a parser succeeds; otherwise ``None``.
    """
    if not companions:
        return None
    for path in companions:
        graph = parse_companion_file(path)
        if graph is None:
            continue
        if graph.module_nets:
            return {key: list(vals) for key, vals in graph.module_nets.items()}
        return _refdes_nets_from_graph(graph)
    return None


def _refdes_nets_from_graph(graph: CompanionGraph) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for binding in graph.bindings:
        bucket = out.setdefault(binding.refdes, [])
        if binding.net not in bucket:
            bucket.append(binding.net)
    return out
