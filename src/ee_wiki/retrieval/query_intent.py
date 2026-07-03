"""Retrieval document-type filter helpers.

AGENTS.md retrieval ranks by project/build scope (build > common > global).
``document_type`` is applied only when the caller or CLI explicitly sets it
(see ``scripts/query.py --document-type`` and API ``document_type``).
Query keywords must not hard-limit retrieval to a single folder type.
"""

from __future__ import annotations


def effective_document_type(
    query: str,
    document_type: str | None,
) -> str | None:
    """Return the caller's explicit ``document_type`` filter, if any.

    Args:
        query: User query (unused; kept for API stability).
        document_type: Optional filter from API/CLI (``schematic``, ``datasheet``, …).

    Returns:
        ``document_type`` when set; otherwise ``None`` (search all types in scope).
    """
    _ = query
    return document_type
