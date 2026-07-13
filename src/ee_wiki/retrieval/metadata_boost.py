"""Metadata-aware keyword boosts for hybrid retrieval ranking."""

from __future__ import annotations

from typing import Any


def metadata_keyword_boost(metadata: dict[str, Any], boost_tokens: list[str]) -> int:
    """Score how many query terms appear in schematic chunk metadata.

    Checks ``interfaces``, ``nets``, ``keywords``, and ``title`` list fields.

    Args:
        metadata: Chunk metadata mapping.
        boost_tokens: Lowercased query terms from :func:`query_boost_tokens`.

    Returns:
        Match count used as a ranking boost (higher is better).
    """
    if not boost_tokens:
        return 0

    haystacks: list[str] = []
    for key in (
        "major_components",
        "interfaces",
        "nets",
        "keywords",
        "supply_voltage",
        "suspected_nets",
        "suspected_parts",
        "steps",
        "case_citations",
    ):
        values = metadata.get(key)
        if isinstance(values, list):
            haystacks.extend(str(value) for value in values)
    title = metadata.get("title")
    if isinstance(title, str):
        haystacks.append(title)

    for key in ("symptom", "root_cause", "case_id", "package"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            haystacks.append(value)

    pin_count = metadata.get("pin_count")
    if pin_count is not None:
        haystacks.append(str(pin_count))

    if not haystacks:
        return 0

    combined = " ".join(haystacks).upper()
    return sum(1 for token in boost_tokens if token.upper() in combined)
