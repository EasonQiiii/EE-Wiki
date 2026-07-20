"""Authoritative-only trace gate for schematic connectivity (ADR 0009 / 0010).

Schematic connectivity has four provenance tiers (see
``ingestion/parsers/schematic_pdf/connectivity/model.py``)::

    cad_netlist > boardview > pdf_geometry > ocr_spatial

Only ``cad_netlist`` / ``boardview`` are board-verified electrical truth. The
lower two tiers are geometry/OCR *guesses*. Failure Analysis (FA) conclusions
must be grounded on verified connectivity, so a half-correct guess is worse
than an explicit refusal: it silently misleads the analyst.

This module is the single enforcement point. Every answer-grade consumer
(HTTP routes, MCP tools, chat trace intercept, and any future FA
orchestration that auto-traces nets) routes trace results through
:func:`apply_authority_gate` so advisory-only data can never masquerade as a
verified trace.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ee_wiki.common.config import SchematicConnectivityConfig

DEFAULT_AUTHORITATIVE_EVIDENCE: frozenset[str] = frozenset(
    {"cad_netlist", "boardview"}
)

ADVISORY_REFUSAL = (
    "No board-verified connectivity (CAD netlist / BoardView) is available for "
    "this scope. Only geometry/OCR guesses exist, which are not reliable enough "
    "to trace connections for failure analysis. Re-ingest the schematic with a "
    "CAD netlist (.net / KiCad) or BoardView (.brd) companion, or verify on the "
    "board directly. No trace is returned to avoid a misleading answer."
)

MODULE_ADVISORY_NOTE = (
    "Module zone labels come from PDF geometry / OCR and are locating hints, "
    "not verified electrical connectivity. Confirm any net with a CAD netlist / "
    "BoardView trace before using it as FA evidence."
)


@dataclass(frozen=True)
class AuthorityPolicy:
    """Policy deciding which connectivity evidence may ground a trace answer.

    Attributes:
        authoritative_evidence: Evidence tags treated as board-verified truth.
        require_authority: When ``True``, answer-grade trace refuses instead of
            returning advisory-only (geometry/OCR) connectivity.
    """

    authoritative_evidence: frozenset[str] = field(
        default_factory=lambda: DEFAULT_AUTHORITATIVE_EVIDENCE
    )
    require_authority: bool = True

    @classmethod
    def from_config(cls, conn: SchematicConnectivityConfig) -> AuthorityPolicy:
        """Build a policy from ``schematic_pdf.connectivity`` config."""
        tags = frozenset(conn.authoritative_evidence) or DEFAULT_AUTHORITATIVE_EVIDENCE
        return cls(
            authoritative_evidence=tags,
            require_authority=conn.require_authority_for_trace,
        )

    def is_authoritative(self, evidence: str | None) -> bool:
        """Return whether an evidence tag counts as board-verified truth."""
        return bool(evidence) and evidence in self.authoritative_evidence


def _partition(
    items: list[dict], policy: AuthorityPolicy
) -> tuple[list[dict], list[dict]]:
    """Split binding dicts into (authoritative, advisory) by evidence tag."""
    authoritative: list[dict] = []
    advisory: list[dict] = []
    for item in items:
        if policy.is_authoritative(item.get("evidence")):
            authoritative.append(item)
        else:
            advisory.append(item)
    return authoritative, advisory


def apply_authority_gate(result: dict, policy: AuthorityPolicy) -> dict:
    """Enforce the authoritative-only trace policy on a query result.

    Handles ``trace_net`` and ``connector_pins`` payloads (net/pin truth
    questions). ``module_nets`` is a geometric locator, not a trace, so it is
    annotated as advisory but never refused (see :func:`annotate_module_nets`).

    Args:
        result: Raw dict from :meth:`ConnectivityQuery.trace_net` /
            ``connector_pins``.
        policy: Active authority policy.

    Returns:
        A new dict with ``authoritative`` / ``authority`` flags. When
        ``policy.require_authority`` and no authoritative binding exists, the
        answer-grade ``pins`` / ``connectors`` are cleared, advisory data is
        moved to ``advisory_pins`` / ``advisory_connectors``, ``found`` is set
        to ``False`` and a refusal ``note`` is attached.
    """
    gated = dict(result)
    pins = list(gated.get("pins") or [])
    connectors = list(gated.get("connectors") or [])

    auth_pins, adv_pins = _partition(pins, policy)
    # Connector-catchment rows are page geometry/OCR — always advisory.
    auth_connectors, adv_connectors = _partition(connectors, policy)

    has_authoritative = bool(auth_pins or auth_connectors)
    gated["authoritative"] = has_authoritative

    if not policy.require_authority:
        gated["authority"] = "authoritative" if has_authoritative else "advisory"
        return gated

    if has_authoritative:
        gated["authority"] = "authoritative"
        gated["pins"] = auth_pins
        gated["pin_count"] = len(auth_pins)
        gated["connectors"] = auth_connectors
        if adv_pins or adv_connectors:
            gated["advisory_pins"] = adv_pins
            gated["advisory_connectors"] = adv_connectors
            gated["note"] = MODULE_ADVISORY_NOTE
        return gated

    if adv_pins or adv_connectors:
        # Advisory-only data existed and was suppressed — refuse a trace.
        gated["authority"] = "insufficient"
        gated["found"] = False
        gated["pins"] = []
        gated["pin_count"] = 0
        gated["connectors"] = []
        gated["advisory_pins"] = adv_pins
        gated["advisory_connectors"] = adv_connectors
        gated["note"] = ADVISORY_REFUSAL
        return gated

    # Nothing found at all (in any tier) — a plain not-found, not a gate refusal.
    gated["authority"] = "not_found"
    return gated


def annotate_module_nets(result: dict, policy: AuthorityPolicy) -> dict:
    """Tag a ``module_nets`` result as advisory (never board-verified truth)."""
    annotated = dict(result)
    annotated["authoritative"] = False
    annotated["authority"] = "advisory"
    if annotated.get("found"):
        annotated["note"] = MODULE_ADVISORY_NOTE
    return annotated
