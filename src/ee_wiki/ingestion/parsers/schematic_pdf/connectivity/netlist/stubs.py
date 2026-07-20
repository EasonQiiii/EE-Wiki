"""Stub netlist parsers for formats reserved but not yet implemented."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import CompanionGraph

logger = get_logger(__name__)


class KicadNetlistStubParser:
    """Placeholder for KiCad ``.kicad_sch`` / ``.kicad_pro`` (ADR 0009 follow-up)."""

    def kind(self) -> str:
        """Return companion kind."""
        return "netlist"

    def supported_extensions(self) -> tuple[str, ...]:
        """Supported suffixes."""
        return (".kicad_sch", ".kicad_pro")

    def parse(self, path: Path) -> CompanionGraph | None:
        """Log and return ``None`` until a real KiCad parser lands."""
        logger.info(
            "KiCad companion present but parser not implemented yet for %s — "
            "falling through to other connectivity sources",
            path.name,
        )
        return None


class AltiumNetlistStubParser:
    """Placeholder for Altium ``.SchDoc`` / project files (ADR 0009 follow-up)."""

    def kind(self) -> str:
        """Return companion kind."""
        return "netlist"

    def supported_extensions(self) -> tuple[str, ...]:
        """Supported suffixes."""
        return (".SchDoc", ".prjpcb", ".PrjPcb")

    def parse(self, path: Path) -> CompanionGraph | None:
        """Log and return ``None`` until a real Altium parser lands."""
        logger.info(
            "Altium companion present but parser not implemented yet for %s — "
            "falling through to other connectivity sources",
            path.name,
        )
        return None
