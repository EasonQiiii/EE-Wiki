"""PDF vector geometry: connector catchment → module nets."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

from ee_wiki.ingestion.parsers.schematic_pdf.connectivity.model import (
    ConnectorBinding,
    PageConnectivity,
)
from ee_wiki.ingestion.parsers.schematic_pdf.signals import (
    OcrToken,
    _label_centers,
    _module_label_tokens,
    _net_centers,
)

_CONNECTOR_REFDES = re.compile(r"^(?:P|J|CN|CON|HDR)\d{1,3}$", re.IGNORECASE)
_DEFAULT_MAX_CONNECTOR_DISTANCE = 90.0
_BELOW_LABEL_PENALTY = 1.5


def _connector_centers(tokens: Sequence[OcrToken]) -> list[tuple[str, float, float]]:
    """Return ``(refdes, cx, cy)`` for connector-like designators on the page."""
    found: list[tuple[str, float, float]] = []
    seen: set[str] = set()
    for token in tokens:
        text = token.text.strip()
        if not _CONNECTOR_REFDES.fullmatch(text):
            continue
        refdes = text.upper()
        if refdes in seen:
            continue
        seen.add(refdes)
        found.append((refdes, token.cx, token.cy))
    return found


def _assign_nets_to_connectors(
    nets: Sequence[str],
    connectors: Sequence[tuple[str, float, float]],
    tokens: Sequence[OcrToken],
    *,
    max_distance: float,
) -> dict[str, list[str]]:
    """Assign each net to the nearest connector within ``max_distance``."""
    assigned: dict[str, list[str]] = {refdes: [] for refdes, _, _ in connectors}
    if not connectors:
        return assigned

    for net in nets:
        points = _net_centers(net, tokens)
        if not points:
            continue
        best: tuple[float, str] | None = None
        for refdes, cx, cy in connectors:
            for nx, ny in points:
                distance = math.hypot(nx - cx, ny - cy)
                if best is None or distance < best[0]:
                    best = (distance, refdes)
        if best is not None and best[0] <= max_distance:
            assigned[best[1]].append(net)

    for refdes in assigned:
        assigned[refdes] = sorted(set(assigned[refdes]), key=str.upper)
    return assigned


def _assign_connectors_to_modules(
    connectors: Sequence[tuple[str, float, float]],
    module_labels: Sequence[str],
    tokens: Sequence[OcrToken],
) -> dict[str, str | None]:
    """Map each connector refdes to the nearest module zone label."""
    label_positions = {
        label: _label_centers(label, tokens) for label in module_labels
    }
    mapping: dict[str, str | None] = {}
    for refdes, cx, cy in connectors:
        best: tuple[float, str] | None = None
        for label, centers in label_positions.items():
            if not centers:
                continue
            tokens_label = set(_module_label_tokens(label))
            for lx, ly in centers:
                distance = math.hypot(cx - lx, cy - ly)
                score = distance + max(0.0, ly - cy) * _BELOW_LABEL_PENALTY
                # Soft preference when connector nets will share prefixes later.
                if any(token in {"USB", "CAN", "SPI", "I2C", "DCMI"} for token in tokens_label):
                    score -= 5.0
                if best is None or score < best[0]:
                    best = (score, label)
        mapping[refdes] = best[1] if best is not None else None
    return mapping


def extract_page_connectivity_from_geometry(
    *,
    page: int,
    module_labels: Sequence[str],
    nets: Sequence[str],
    ocr_tokens: Sequence[OcrToken],
    max_connector_distance: float = _DEFAULT_MAX_CONNECTOR_DISTANCE,
) -> PageConnectivity | None:
    """Build module↔net bindings via connector catchment on PDF OCR tokens.

    Args:
        page: 1-based page number.
        module_labels: Zone titles from OCR fidelity.
        nets: Normalized net names on the page.
        ocr_tokens: Word boxes for the page.
        max_connector_distance: Max distance from net label to connector center.

    Returns:
        Page connectivity when at least one connector is found; otherwise ``None``.
    """
    connectors = _connector_centers(ocr_tokens)
    if not connectors:
        return None

    nets_by_connector = _assign_nets_to_connectors(
        nets,
        connectors,
        ocr_tokens,
        max_distance=max_connector_distance,
    )
    connector_modules = _assign_connectors_to_modules(
        connectors,
        module_labels,
        ocr_tokens,
    )

    module_nets: dict[str, set[str]] = {label: set() for label in module_labels}
    bindings: list[ConnectorBinding] = []
    for refdes, _cx, _cy in connectors:
        connector_nets = nets_by_connector.get(refdes, [])
        module = connector_modules.get(refdes)
        bindings.append(
            ConnectorBinding(
                refdes=refdes,
                module=module,
                nets=tuple(connector_nets),
                evidence="pdf_geometry",
            )
        )
        if module and connector_nets:
            module_nets.setdefault(module, set()).update(connector_nets)

    # Prefer nets whose prefix matches the module tokens when two modules compete —
    # currently each net is owned by one connector, so union is enough.
    resolved = {
        label: sorted(values, key=str.upper)
        for label, values in module_nets.items()
        if values
    }
    if not resolved and not any(binding.nets for binding in bindings):
        return None

    return PageConnectivity(
        page=page,
        source="pdf_geometry",
        connectors=tuple(bindings),
        module_nets=resolved,
    )
