"""Registry of companion parsers for netlist and boardview files."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.boardview.landrex_brd import (
    LandrexBrdParser,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import CompanionGraph
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.netlist.generic_net import (
    GenericNetlistParser,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.netlist.stubs import (
    AltiumNetlistStubParser,
    KicadNetlistStubParser,
)

logger = get_logger(__name__)

_PARSERS: tuple[object, ...] = (
    LandrexBrdParser(),
    GenericNetlistParser(),
    KicadNetlistStubParser(),
    AltiumNetlistStubParser(),
)


def parsers_for_suffix(suffix: str) -> list[object]:
    """Return registered parsers that claim ``suffix`` (case-insensitive)."""
    needle = suffix.lower()
    matched: list[object] = []
    for parser in _PARSERS:
        extensions = tuple(
            ext.lower() for ext in parser.supported_extensions()  # type: ignore[attr-defined]
        )
        if needle in extensions:
            matched.append(parser)
    return matched


def parse_companion_file(path: Path) -> CompanionGraph | None:
    """Try registered parsers for ``path`` until one returns a graph.

    Args:
        path: Companion file path.

    Returns:
        First successful :class:`CompanionGraph`, or ``None``.
    """
    candidates = parsers_for_suffix(path.suffix)
    if not candidates:
        logger.info(
            "No companion parser registered for %s — skipping",
            path.name,
        )
        return None
    for parser in candidates:
        graph = parser.parse(path)  # type: ignore[attr-defined]
        if graph is not None:
            return graph
    return None
