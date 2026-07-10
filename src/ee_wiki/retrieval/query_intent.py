"""Retrieval document-type filter helpers.

AGENTS.md retrieval ranks by project/build scope (build > common > global).
``document_type`` is applied only when the caller or CLI explicitly sets it
(see ``scripts/query.py --document-type`` and API ``document_type``).
Query keywords must not hard-limit retrieval to a single folder type.
"""

from __future__ import annotations

import re

_BOARD_PIN_PATTERN = re.compile(
    r"(?:pin|pins|引脚|脚)",
    re.IGNORECASE,
)
_INTERFACE_PATTERN = re.compile(
    r"(?:lcd|display|touchscreen|touch|触摸屏|接口|interface|connector|header|排针|屏幕|rmii|i2s|uart|spi|i2c|eth|usb)",
    re.IGNORECASE,
)


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


def is_board_interface_pin_query(query: str) -> bool:
    """Return whether ``query`` asks for on-board interface pins (not a part DS).

    Examples: ``lcd的pin有哪些``, ``RMII interface pins``, ``触摸屏引脚``.
    """
    if not query.strip():
        return False
    return bool(
        _BOARD_PIN_PATTERN.search(query)
        and _INTERFACE_PATTERN.search(query)
    )
