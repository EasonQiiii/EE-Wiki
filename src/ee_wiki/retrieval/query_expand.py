"""Query expansion hook — intentionally a no-op.

Retrieval uses the user's query as-is. Schematic evidence comes from indexed
OCR content (module labels, net names), not from configured signal aliases.
"""

from __future__ import annotations


def expand_hw_query(query: str) -> str:
    """Return the query unchanged."""
    return query
