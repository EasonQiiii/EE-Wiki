"""Connectivity evidence models for schematic ingest."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConnectivitySource = Literal["cad_netlist", "pdf_geometry", "ocr_spatial"]


@dataclass(frozen=True)
class ConnectorBinding:
    """One connector designator bound to a module and nets."""

    refdes: str
    module: str | None
    nets: tuple[str, ...]
    evidence: ConnectivitySource


@dataclass(frozen=True)
class PageConnectivity:
    """Connectivity result for one schematic page."""

    page: int
    source: ConnectivitySource
    connectors: tuple[ConnectorBinding, ...] = ()
    module_nets: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class SchematicConnectivity:
    """Document-level connectivity sidecar payload."""

    source_file: str
    pages: list[PageConnectivity] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize for ``*.connectivity.json``."""
        return {
            "source_file": self.source_file,
            "pages": [
                {
                    "page": page.page,
                    "source": page.source,
                    "connectors": [
                        {
                            "refdes": connector.refdes,
                            "module": connector.module,
                            "nets": list(connector.nets),
                            "evidence": connector.evidence,
                        }
                        for connector in page.connectors
                    ],
                    "module_nets": page.module_nets,
                }
                for page in self.pages
            ],
        }
