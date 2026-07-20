"""Best-effort generic ``.net`` text netlist parser.

Recognizes a minimal line-oriented format used by fixtures and simple exports:

=======
# comments allowed
NET_NAME REFDES PIN
=======

Also attempts a light KiCad s-expression extract ``(net … (node REF PIN))``.
Unrecognized content returns ``None`` so other sources can fill in.
"""

from __future__ import annotations

import re
from pathlib import Path

from ee_wiki.common.logging import get_logger
from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    CompanionGraph,
    PinNetBinding,
)

logger = get_logger(__name__)

_LINE_RE = re.compile(
    r"^(?P<net>[A-Za-z_][\w./+\-*]*)\s+(?P<refdes>[A-Za-z]+\d[\w]*)\s+(?P<pin>\S+)\s*$"
)
_KICAD_NODE_RE = re.compile(
    r'\(node\s+\(ref\s+"([^"]+)"\)\s+\(pin\s+"([^"]+)"\)\)',
)


def _parse_line_oriented(text: str) -> list[PinNetBinding]:
    bindings: list[PinNetBinding] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("(") or line.startswith("$"):
            return []  # likely another format; let other parsers try
        match = _LINE_RE.match(line)
        if not match:
            continue
        bindings.append(
            PinNetBinding(
                refdes=match.group("refdes"),
                pin=match.group("pin"),
                net=match.group("net"),
                evidence="cad_netlist",
            )
        )
    return bindings


def _parse_kicad_sexpr(text: str) -> list[PinNetBinding]:
    if "(export" not in text and "(netlist" not in text and "(net " not in text:
        return []
    bindings: list[PinNetBinding] = []
    # Split on (net blocks roughly
    parts = re.split(r"\(net\s+", text)
    for part in parts[1:]:
        name_match = re.search(r'\(name\s+"([^"]+)"\)', part)
        if not name_match:
            name_match = re.search(r"\(name\s+([^\s)]+)\)", part)
        if not name_match:
            continue
        net = name_match.group(1)
        if net.startswith("/") and len(net) > 1:
            net = net.rsplit("/", 1)[-1]
        for node in _KICAD_NODE_RE.finditer(part):
            bindings.append(
                PinNetBinding(
                    refdes=node.group(1),
                    pin=node.group(2),
                    net=net,
                    evidence="cad_netlist",
                )
            )
    return bindings


def parse_generic_netlist(path: Path) -> CompanionGraph | None:
    """Parse a generic text netlist into pin–net bindings.

    Args:
        path: Path to a ``.net`` (or similarly named) text file.

    Returns:
        :class:`CompanionGraph` or ``None`` when unrecognized.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Cannot read netlist %s: %s", path, exc)
        return None

    bindings = _parse_line_oriented(text)
    if not bindings:
        bindings = _parse_kicad_sexpr(text)
    if not bindings:
        logger.info(
            "Netlist %s not recognized by generic parser — skipping",
            path.name,
        )
        return None

    logger.info(
        "Parsed netlist %s: %d pin–net binding(s) (evidence=cad_netlist)",
        path.name,
        len(bindings),
    )
    return CompanionGraph(
        evidence="cad_netlist",
        source_path=str(path),
        bindings=bindings,
    )


class GenericNetlistParser:
    """Best-effort parser for flat text ``.net`` companions."""

    def kind(self) -> str:
        """Return companion kind."""
        return "netlist"

    def supported_extensions(self) -> tuple[str, ...]:
        """Supported suffixes."""
        return (".net",)

    def parse(self, path: Path) -> CompanionGraph | None:
        """Parse ``path`` as a generic netlist."""
        return parse_generic_netlist(path)
