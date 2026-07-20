"""Heuristic power-rail detection and ``supplies`` / ``derived_from`` extraction.

V3 P3 builds a best-effort power tree from schematic page co-occurrence and
datasheet ``supply_voltage`` metadata. There is **no CAD netlist parser**;
edges are probabilistic naming + co-occurrence hints and must be treated as
candidates, not board truth.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import DATASHEET_DOCUMENT_TYPE, SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.common.types import Chunk, DataLayoutConfig
from ee_wiki.graph.assemble import GraphAssembler
from ee_wiki.graph.ids import (
    component_node_id,
    document_node_id,
    net_node_id,
    part_node_id,
)
from ee_wiki.graph.models import EDGE_DERIVED_FROM, EDGE_SUPPLIES, GraphEdge
from ee_wiki.ingestion.keywords import is_designator, is_part_number_keyword

logger = get_logger(__name__)

# Exact / known rail tokens (normalized uppercase, separators stripped for match).
_KNOWN_RAILS = frozenset(
    {
        "VDD",
        "VCC",
        "VSS",
        "VEE",
        "VBAT",
        "VBUS",
        "VIN",
        "VOUT",
        "VSYS",
        "VCORE",
        "AVDD",
        "DVDD",
        "AVCC",
        "DVCC",
        "PVDD",
        "HVDD",
        "IOVDD",
        "VDDA",
        "VDDIO",
        "VREF",
        "VPP",
        "GND",
        "AGND",
        "DGND",
        "PGND",
        "3V3",
        "1V8",
        "1V2",
        "1V0",
        "5V",
        "12V",
        "24V",
        "48V",
        "+3V3",
        "+1V8",
        "+5V",
        "+12V",
        "-5V",
        "-12V",
    }
)

_RAIL_PREFIX_RE = re.compile(
    r"^(?:NET_)?(?:"
    r"VDD|VCC|VSS|VEE|VBAT|VBUS|VIN|VOUT|VSYS|VCORE|"
    r"AVDD|DVDD|AVCC|DVCC|PVDD|HVDD|IOVDD|VDDA|VDDIO|VREF|VPP|"
    r"GND|AGND|DGND|PGND"
    r")",
    re.IGNORECASE,
)
_VOLTAGE_TOKEN_RE = re.compile(
    r"^[+\-]?(?:\d+V\d+|\d+\.?\d*V)$",
    re.IGNORECASE,
)
# Explicit regulator / PMIC reference prefixes (not bare ``U`` — MCUs are also ``U``).
_STRONG_REGULATOR_RE = re.compile(
    r"^(?:VR|REG|LDO|PMIC|DCDC|BUCK|BOOST)\d+[A-Z]?$",
    re.IGNORECASE,
)
_U_DESIGNATOR_RE = re.compile(r"^U\d+[A-Z]?$", re.IGNORECASE)
_PASSIVE_DESIGNATOR_RE = re.compile(
    r"^(?:R|C|L|FB|TP|J|P|SW|TEST)\d+[A-Z]?$",
    re.IGNORECASE,
)
_INPUT_ROLE_HINTS = ("VIN", "VBAT", "VBUS", "VSYS", "VCC", "5V", "12V", "24V", "48V")
_GROUND_NAMES = frozenset({"GND", "AGND", "DGND", "PGND", "VSS"})


def _normalize_net_token(name: str) -> str:
    return name.strip().upper().replace(" ", "")


def is_rail_like_net(name: str) -> bool:
    """Return whether a net name looks like a power / ground rail.

    Args:
        name: Schematic net name from page metadata.

    Returns:
        ``True`` when naming heuristics classify the net as a rail candidate.
    """
    token = _normalize_net_token(name)
    if not token or token in {"NC", "N/C"}:
        return False
    bare = token.removeprefix("NET_")
    if bare in _KNOWN_RAILS or token in _KNOWN_RAILS:
        return True
    if _VOLTAGE_TOKEN_RE.match(bare) or _VOLTAGE_TOKEN_RE.match(token):
        return True
    if _RAIL_PREFIX_RE.match(bare):
        return True
    return False


def is_ground_rail(name: str) -> bool:
    """Return whether ``name`` is a ground / return rail."""
    bare = _normalize_net_token(name).removeprefix("NET_")
    return bare in _GROUND_NAMES or bare.startswith("GND")


def is_regulator_designator(designator: str) -> bool:
    """Return whether a designator is an explicit regulator / PMIC candidate.

    Bare ``U*`` IC designators are **not** always regulators (MCUs share the
    prefix). Use :func:`classify_page_power_roles` for page-level soft rules.
    """
    return bool(_STRONG_REGULATOR_RE.match(designator.strip()))


def is_load_designator(designator: str) -> bool:
    """Return whether a designator may be treated as a load (not passive)."""
    cleaned = designator.strip()
    if not cleaned or not is_designator(cleaned):
        return False
    if _PASSIVE_DESIGNATOR_RE.match(cleaned):
        return False
    if is_regulator_designator(cleaned):
        return False
    return True


def _designator_sort_key(designator: str) -> tuple[int, str]:
    match = re.match(r"^([A-Z]+)(\d+)", designator.strip().upper())
    if match:
        return (int(match.group(2)), match.group(0))
    return (10**9, designator.strip().upper())


def classify_page_power_roles(
    designators: list[str],
    *,
    has_input_and_output: bool,
) -> tuple[list[str], list[str]]:
    """Split page designators into regulator vs load candidates.

    Strong prefixes (``VR``, ``LDO``, …) are always regulators. When the page
    has both input-like and output-like rails, the numerically lowest ``U*``
    is treated as the soft regulator (typical LDO/PMIC) and other ``U*`` as
    loads (typical MCU/SoC). Without an input/output pair, only strong
    regulators are used — bare ``U*`` stay loads so we do not invent a
    converter topology.

    Args:
        designators: Schematic designators on the page.
        has_input_and_output: Whether both input- and output-like rails exist.

    Returns:
        ``(regulators, loads)`` lists (original casing preserved).
    """
    strong = [d for d in designators if is_regulator_designator(d)]
    u_ics = [d for d in designators if _U_DESIGNATOR_RE.match(d.strip())]
    regulators = list(strong)
    if has_input_and_output and not regulators and u_ics:
        regulators = [min(u_ics, key=_designator_sort_key)]

    reg_upper = {d.strip().upper() for d in regulators}
    loads = [
        d
        for d in designators
        if d.strip().upper() not in reg_upper and is_load_designator(d)
    ]
    # Soft-regulator U* that did not become the chosen regulator are loads.
    for u_ic in u_ics:
        if u_ic.strip().upper() not in reg_upper and u_ic not in loads:
            loads.append(u_ic)
    return regulators, loads


def voltage_hint_from_name(name: str) -> str:
    """Extract a normalized voltage hint (e.g. ``3.3V``) from a rail name."""
    token = _normalize_net_token(name).removeprefix("NET_")
    # Forms like 3V3 / 1V8
    compact = re.match(r"^[+\-]?(\d+)V(\d+)$", token, re.IGNORECASE)
    if compact:
        return f"{compact.group(1)}.{compact.group(2)}V"
    # Forms like 3.3V / 5V / +12V
    dotted = re.match(r"^[+\-]?(\d+\.?\d*)V$", token, re.IGNORECASE)
    if dotted:
        return f"{dotted.group(1)}V"
    embedded = re.search(r"(\d+)V(\d+)", token, re.IGNORECASE)
    if embedded:
        return f"{embedded.group(1)}.{embedded.group(2)}V"
    embedded_simple = re.search(r"(\d+\.?\d*)V", token, re.IGNORECASE)
    if embedded_simple:
        return f"{embedded_simple.group(1)}V"
    return ""


def rail_role(name: str) -> str:
    """Return a coarse heuristic role: ``ground``, ``input``, ``output``, or ``rail``."""
    bare = _normalize_net_token(name).removeprefix("NET_")
    if is_ground_rail(bare):
        return "ground"
    upper = bare.upper()
    # Explicit output-like tokens win over input (e.g. VCC3V3).
    if any(
        upper == hint or upper.endswith(hint) or hint in upper
        for hint in ("VOUT", "3V3", "1V8", "1V2", "1V0", "VCORE", "IOVDD")
    ):
        return "output"
    if upper in {"VDD", "VDDA", "DVDD", "AVDD"} or upper.startswith("VDD"):
        return "output"
    if any(
        upper == hint or upper.startswith(hint)
        for hint in _INPUT_ROLE_HINTS
    ):
        return "input"
    return "rail"


def _match_rail_to_voltage(rail_name: str, voltages: list[str]) -> bool:
    """Return whether a rail name is consistent with any datasheet supply voltage."""
    hint = voltage_hint_from_name(rail_name)
    if not hint:
        return False
    hint_norm = hint.upper().replace(" ", "")
    for voltage in voltages:
        v = voltage.strip().upper().replace(" ", "")
        if not v:
            continue
        if hint_norm in v or v in hint_norm:
            return True
        # Range like 2V-3.6V: match if rail hint equals either end or is inside loosely
        if "-" in v:
            parts = v.split("-", 1)
            if hint_norm in parts:
                return True
    return False


@dataclass(frozen=True)
class PowerExtractionStats:
    """Counts from a power-tree extraction pass."""

    rails: int = 0
    supplies_edges: int = 0
    derived_from_edges: int = 0


def add_power_semantics(
    asm: GraphAssembler,
    chunks: list[Chunk],
    *,
    layout: DataLayoutConfig,
) -> PowerExtractionStats:
    """Add Rail nodes and ``supplies`` / ``derived_from`` edges from chunk metadata.

    Schematic pages: rail-like nets become Rail nodes linked to Net via
    ``derived_from`` (Rail derived_from Net identity). Regulator designators
    co-occurring with rails get ``supplies`` to output-like rails; rails
    ``supplies`` non-regulator loads on the same page. When both input- and
    output-like rails share a page with a regulator, output ``derived_from``
    input.

    Datasheet chunks: part-number components with ``supply_voltage`` link to
    matching Rail nodes in the same product/project when a voltage hint matches.

    Args:
        asm: Graph assembler already populated with components/nets/documents.
        chunks: Indexed chunks (schematic + datasheet).
        layout: Path naming configuration (reserved segments for scope rules).

    Returns:
        Extraction statistics for logging / fingerprints.
    """
    global_segment = layout.global_segment
    common_segment = layout.common_segment
    rail_count = 0
    supplies_count = 0
    derived_count = 0
    # Track rails created per (product, project, build, name) for datasheet linking.
    seen_rails: set[str] = set()

    for chunk in chunks:
        meta = chunk.metadata
        if not meta.product or not meta.source_file:
            continue
        if meta.document_type != SCHEMATIC_DOCUMENT_TYPE:
            continue
        if not meta.nets:
            continue

        page = chunk.citation.page or meta.page
        doc_id = document_node_id(meta.product, meta.project, meta.build, meta.source_file)
        if doc_id not in asm.graph.nodes:
            continue

        designators = [
            t for t in (meta.major_components or []) if is_designator(t)
        ]
        rail_nets = [n for n in meta.nets if is_rail_like_net(n)]
        if not rail_nets:
            continue

        # Provisional roles from net names (before rail nodes exist).
        provisional_roles = {n: rail_role(n) for n in rail_nets}
        has_input = any(r == "input" for r in provisional_roles.values())
        has_output = any(
            r in {"output", "rail"} and not is_ground_rail(n)
            for n, r in provisional_roles.items()
        )
        regulators, loads = classify_page_power_roles(
            designators,
            has_input_and_output=has_input and has_output,
        )
        rail_nodes: list[tuple[str, Any]] = []

        for net_name in rail_nets:
            role = rail_role(net_name)
            hint = voltage_hint_from_name(net_name)
            rail = asm.ensure_rail(
                product=meta.product,
                project=meta.project,
                build=meta.build,
                rail_name=net_name,
                doc_id=doc_id,
                page=page,
                voltage_hint=hint,
                role=role,
            )
            if rail.id not in seen_rails:
                seen_rails.add(rail.id)
                rail_count += 1
            # Ensure Net exists (build pass usually created it) then link identity.
            net = asm.ensure_net(
                product=meta.product,
                project=meta.project,
                build=meta.build,
                net_name=net_name,
                doc_id=doc_id,
                page=page,
            )
            before = len(asm.graph.edges)
            asm.add_edge(
                GraphEdge(
                    source=rail.id,
                    target=net.id,
                    type=EDGE_DERIVED_FROM,
                    product=meta.product,
                    project=meta.project,
                    build=meta.build,
                    attributes={"kind": "rail_of_net", "page": page},
                )
            )
            if len(asm.graph.edges) > before:
                derived_count += 1
            rail_nodes.append((net_name, rail))

        input_rails = [
            (name, node)
            for name, node in rail_nodes
            if node.attributes.get("role") == "input"
        ]
        output_rails = [
            (name, node)
            for name, node in rail_nodes
            if node.attributes.get("role") in {"output", "rail"}
            and not is_ground_rail(name)
        ]
        # If no role split, treat non-ground as outputs for load linking.
        if not output_rails:
            output_rails = [
                (name, node)
                for name, node in rail_nodes
                if not is_ground_rail(name)
            ]

        for reg in regulators:
            reg_id = component_node_id(meta.product, meta.project, meta.build, reg)
            if reg_id not in asm.graph.nodes:
                continue
            targets = output_rails or [
                (n, r) for n, r in rail_nodes if not is_ground_rail(n)
            ]
            for _name, rail in targets:
                before = len(asm.graph.edges)
                asm.add_edge(
                    GraphEdge(
                        source=reg_id,
                        target=rail.id,
                        type=EDGE_SUPPLIES,
                        product=meta.product,
                        project=meta.project,
                        build=meta.build,
                        attributes={
                            "kind": "regulator_to_rail",
                            "page": page,
                            "heuristic": True,
                        },
                    )
                )
                if len(asm.graph.edges) > before:
                    supplies_count += 1

        for _name, rail in output_rails:
            for load in loads:
                load_id = component_node_id(meta.product, meta.project, meta.build, load)
                if load_id not in asm.graph.nodes:
                    continue
                # Prefer pages where component already connects_to the net.
                net_id = net_node_id(meta.product, meta.project, meta.build, _name)
                co_connected = any(
                    e.type == "connects_to"
                    and (
                        (e.source == load_id and e.target == net_id)
                        or (e.target == load_id and e.source == net_id)
                    )
                    for e in asm.graph.edges
                )
                if not co_connected and loads:
                    # Still link when only one non-ground rail on the page.
                    if len(output_rails) > 1:
                        continue
                before = len(asm.graph.edges)
                asm.add_edge(
                    GraphEdge(
                        source=rail.id,
                        target=load_id,
                        type=EDGE_SUPPLIES,
                        product=meta.product,
                        project=meta.project,
                        build=meta.build,
                        attributes={
                            "kind": "rail_to_load",
                            "page": page,
                            "heuristic": True,
                        },
                    )
                )
                if len(asm.graph.edges) > before:
                    supplies_count += 1

        # Rail hierarchy: output derived_from input when a regulator is present.
        if regulators and input_rails and output_rails:
            for _in_name, in_rail in input_rails:
                for _out_name, out_rail in output_rails:
                    if in_rail.id == out_rail.id:
                        continue
                    before = len(asm.graph.edges)
                    asm.add_edge(
                        GraphEdge(
                            source=out_rail.id,
                            target=in_rail.id,
                            type=EDGE_DERIVED_FROM,
                            product=meta.product,
                            project=meta.project,
                            build=meta.build,
                            attributes={
                                "kind": "rail_hierarchy",
                                "page": page,
                                "via_regulator": regulators[0].upper(),
                                "heuristic": True,
                            },
                        )
                    )
                    if len(asm.graph.edges) > before:
                        derived_count += 1

    # Datasheet supply_voltage → part needs matching rail (rail supplies part).
    for chunk in chunks:
        meta = chunk.metadata
        if meta.document_type != DATASHEET_DOCUMENT_TYPE:
            continue
        voltages = list(meta.supply_voltage or [])
        if not voltages:
            continue
        parts = [t for t in meta.keywords if is_part_number_keyword(t)]
        if not parts:
            continue
        # Match against rails in the same product only (never across products).
        # A product-common datasheet (project == common) may match any project's
        # rails within that product; a project-scoped datasheet stays in its project.
        candidate_rails = [
            node
            for node in asm.graph.nodes.values()
            if node.type == "Rail"
            and node.product == meta.product
            and (meta.project == common_segment or node.project == meta.project)
        ]
        for part in parts:
            part_id = part_node_id(part)
            if part_id not in asm.graph.nodes:
                doc_id = document_node_id(
                    meta.product, meta.project, meta.build, meta.source_file
                )
                if doc_id not in asm.graph.nodes:
                    continue
                asm.ensure_part(
                    part_number=part,
                    product=meta.product,
                    project=meta.project,
                    build=meta.build,
                    doc_id=doc_id,
                    global_segment=global_segment,
                )
            for rail in candidate_rails:
                rail_name = str(rail.attributes.get("name", ""))
                if not _match_rail_to_voltage(rail_name, voltages):
                    continue
                before = len(asm.graph.edges)
                asm.add_edge(
                    GraphEdge(
                        source=rail.id,
                        target=part_id,
                        type=EDGE_SUPPLIES,
                        product=meta.product,
                        project=meta.project,
                        build=meta.build,
                        attributes={
                            "kind": "datasheet_supply",
                            "supply_voltage": voltages,
                            "heuristic": True,
                        },
                    )
                )
                if len(asm.graph.edges) > before:
                    supplies_count += 1

    stats = PowerExtractionStats(
        rails=rail_count,
        supplies_edges=supplies_count,
        derived_from_edges=derived_count,
    )
    logger.info(
        "Power tree extraction: %d rail(s), %d supplies edge(s), %d derived_from edge(s)",
        stats.rails,
        stats.supplies_edges,
        stats.derived_from_edges,
    )
    return stats
