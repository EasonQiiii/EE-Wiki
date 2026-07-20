"""Read-only query over schematic ``*.connectivity.json`` sidecars (ADR 0009)."""

from __future__ import annotations

from ee_wiki.connectivity.authority import (
    ADVISORY_REFUSAL,
    AuthorityPolicy,
    apply_authority_gate,
)
from ee_wiki.connectivity.intent import TraceIntent, detect_trace_intent
from ee_wiki.connectivity.query import ConnectivityQuery, open_connectivity_query
from ee_wiki.connectivity.store import (
    ConnectivityDocument,
    ConnectivityStoreError,
    load_connectivity_documents,
)

__all__ = [
    "ADVISORY_REFUSAL",
    "AuthorityPolicy",
    "ConnectivityDocument",
    "ConnectivityQuery",
    "ConnectivityStoreError",
    "TraceIntent",
    "apply_authority_gate",
    "detect_trace_intent",
    "load_connectivity_documents",
    "open_connectivity_query",
]
