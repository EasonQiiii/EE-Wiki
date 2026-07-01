"""Serialize core types for persistence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ee_wiki.common.types import Metadata


def metadata_to_dict(metadata: Metadata) -> dict[str, Any]:
    """Convert :class:`Metadata` to a JSON-serializable mapping.

    Args:
        metadata: Document metadata instance.

    Returns:
        Dictionary suitable for ``json.dump``.
    """
    return asdict(metadata)
