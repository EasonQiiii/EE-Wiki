"""Connectivity evidence models for schematic ingest (ADR 0007 / 0009)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConnectivitySource = Literal[
    "cad_netlist",
    "boardview",
    "pdf_geometry",
    "ocr_spatial",
]

SIDECAR_SCHEMA_VERSION = 2

# Higher rank wins on conflicting (refdes, pin) → net assignments.
EVIDENCE_PRIORITY: dict[ConnectivitySource, int] = {
    "cad_netlist": 4,
    "boardview": 3,
    "pdf_geometry": 2,
    "ocr_spatial": 1,
}


@dataclass(frozen=True)
class PinNetBinding:
    """One refdes pin connected to a net, with evidence tag."""

    refdes: str
    pin: str
    net: str
    evidence: ConnectivitySource

    def to_dict(self) -> dict:
        """Serialize for sidecar ``nets`` / ``parts`` entries."""
        return {
            "refdes": self.refdes,
            "pin": self.pin,
            "net": self.net,
            "evidence": self.evidence,
        }


@dataclass
class CompanionGraph:
    """Pin–net graph from one companion file (netlist or boardview)."""

    evidence: ConnectivitySource
    source_path: str
    bindings: list[PinNetBinding] = field(default_factory=list)
    module_nets: dict[str, list[str]] = field(default_factory=dict)

    def nets_index(self) -> dict[str, list[PinNetBinding]]:
        """Group bindings by net name."""
        out: dict[str, list[PinNetBinding]] = {}
        for binding in self.bindings:
            out.setdefault(binding.net, []).append(binding)
        return out

    def parts_index(self) -> dict[str, list[PinNetBinding]]:
        """Group bindings by refdes."""
        out: dict[str, list[PinNetBinding]] = {}
        for binding in self.bindings:
            out.setdefault(binding.refdes, []).append(binding)
        return out


@dataclass(frozen=True)
class CompanionManifest:
    """Discovered companion paths next to a schematic PDF."""

    netlist: str | None = None
    boardview: str | None = None

    def to_dict(self) -> dict:
        """Serialize for sidecar ``companions``."""
        return {"netlist": self.netlist, "boardview": self.boardview}


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
    """Document-level connectivity sidecar payload (schema v2)."""

    source_file: str
    pages: list[PageConnectivity] = field(default_factory=list)
    companions: CompanionManifest = field(default_factory=CompanionManifest)
    sources_used: list[ConnectivitySource] = field(default_factory=list)
    nets: dict[str, list[PinNetBinding]] = field(default_factory=dict)
    parts: dict[str, list[PinNetBinding]] = field(default_factory=dict)
    schema_version: int = SIDECAR_SCHEMA_VERSION

    def to_dict(self) -> dict:
        """Serialize for ``*.connectivity.json``."""
        return {
            "schema_version": self.schema_version,
            "source_file": self.source_file,
            "companions": self.companions.to_dict(),
            "sources_used": list(self.sources_used),
            "nets": {
                net: [
                    {"refdes": b.refdes, "pin": b.pin, "evidence": b.evidence}
                    for b in bindings
                ]
                for net, bindings in sorted(self.nets.items())
            },
            "parts": {
                refdes: {
                    "pins": [
                        {"pin": b.pin, "net": b.net, "evidence": b.evidence}
                        for b in pins
                    ]
                }
                for refdes, pins in sorted(self.parts.items())
            },
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

    @classmethod
    def from_dict(cls, data: dict) -> SchematicConnectivity:
        """Deserialize a sidecar JSON object into :class:`SchematicConnectivity`.

        Args:
            data: Parsed JSON mapping from ``*.connectivity.json``.

        Returns:
            Populated connectivity document (schema v1 pages-only or v2).
        """
        companions_raw = data.get("companions") or {}
        companions = CompanionManifest(
            netlist=companions_raw.get("netlist"),
            boardview=companions_raw.get("boardview"),
        )
        nets: dict[str, list[PinNetBinding]] = {}
        for net_name, entries in (data.get("nets") or {}).items():
            bindings: list[PinNetBinding] = []
            for entry in entries or []:
                bindings.append(
                    PinNetBinding(
                        refdes=str(entry.get("refdes", "")),
                        pin=str(entry.get("pin", "")),
                        net=str(net_name),
                        evidence=entry.get("evidence") or "boardview",  # type: ignore[arg-type]
                    )
                )
            if bindings:
                nets[str(net_name)] = bindings

        parts: dict[str, list[PinNetBinding]] = {}
        for refdes, part_body in (data.get("parts") or {}).items():
            pins_raw = (part_body or {}).get("pins") or []
            bindings = []
            for entry in pins_raw:
                bindings.append(
                    PinNetBinding(
                        refdes=str(refdes),
                        pin=str(entry.get("pin", "")),
                        net=str(entry.get("net", "")),
                        evidence=entry.get("evidence") or "boardview",  # type: ignore[arg-type]
                    )
                )
            if bindings:
                parts[str(refdes)] = bindings

        pages: list[PageConnectivity] = []
        for page_raw in data.get("pages") or []:
            connectors = tuple(
                ConnectorBinding(
                    refdes=str(c.get("refdes", "")),
                    module=c.get("module"),
                    nets=tuple(str(n) for n in (c.get("nets") or [])),
                    evidence=c.get("evidence") or "pdf_geometry",  # type: ignore[arg-type]
                )
                for c in (page_raw.get("connectors") or [])
            )
            pages.append(
                PageConnectivity(
                    page=int(page_raw.get("page", 0)),
                    source=page_raw.get("source") or "ocr_spatial",  # type: ignore[arg-type]
                    connectors=connectors,
                    module_nets={
                        str(k): [str(n) for n in v]
                        for k, v in (page_raw.get("module_nets") or {}).items()
                    },
                )
            )

        sources_used = [
            str(s) for s in (data.get("sources_used") or [])  # type: ignore[misc]
        ]
        return cls(
            source_file=str(data.get("source_file", "")),
            pages=pages,
            companions=companions,
            sources_used=sources_used,  # type: ignore[arg-type]
            nets=nets,
            parts=parts,
            schema_version=int(data.get("schema_version", 1)),
        )
