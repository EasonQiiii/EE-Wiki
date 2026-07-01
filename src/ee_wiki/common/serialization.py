"""Serialize core types for persistence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ee_wiki.common.types import Metadata

SCHEMATIC_DOCUMENT_TYPE = "schematic"
SCHEMATIC_ONLY_FIELDS = ("major_components", "nets", "interfaces")


def metadata_to_dict(metadata: Metadata) -> dict[str, Any]:
    """Convert :class:`Metadata` to a JSON-serializable mapping.

    Schematic-only fields (``major_components``, ``nets``, ``interfaces``) are
    included only when ``document_type`` is ``schematic`` (``sch/`` folder).

    Args:
        metadata: Document metadata instance.

    Returns:
        Dictionary suitable for ``json.dump``.
    """
    data = asdict(metadata)

    if metadata.document_type != SCHEMATIC_DOCUMENT_TYPE:
        for key in SCHEMATIC_ONLY_FIELDS:
            data.pop(key, None)

    if not metadata.target_file:
        data.pop("target_file", None)

    return data
