"""Protocols for schematic companion parsers (netlist / boardview).

See docs/adr/0009-multi-source-schematic-map.md. Implementations live under
``ingestion/parsers/schematic_pdf/connectivity/`` and return
``CompanionGraph`` (defined there) — typed as ``Any`` here so ``protocols/``
does not import feature modules.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol

CompanionKind = Literal["netlist", "boardview"]


class ConnectivityCompanionParser(Protocol):
    """Parse a companion file next to a schematic PDF into a pin–net graph.

    Implementations must not raise for unsupported content — return ``None``
    and log so ingest can fall through to other sources (ADR 0009).
    """

    def kind(self) -> CompanionKind:
        """Return ``netlist`` or ``boardview``."""
        ...

    def supported_extensions(self) -> tuple[str, ...]:
        """File suffixes including the leading dot (case-insensitive match)."""
        ...

    def parse(self, path: Path) -> Any | None:
        """Parse ``path`` into a companion pin–net graph, or ``None``.

        Args:
            path: Absolute or relative path to a companion file.

        Returns:
            Parsed graph (``CompanionGraph``) with evidence tags, or ``None``
            when the format is unrecognized or not yet implemented.
        """
        ...
