"""Schematic netlist companion parsers."""

from __future__ import annotations

from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.netlist.generic_net import (
    GenericNetlistParser,
)
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.netlist.stubs import (
    AltiumNetlistStubParser,
    KicadNetlistStubParser,
)

__all__ = [
    "AltiumNetlistStubParser",
    "GenericNetlistParser",
    "KicadNetlistStubParser",
]
