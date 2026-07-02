"""Serialize core types for persistence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ee_wiki.common.types import Chunk, Citation, Metadata

SCHEMATIC_DOCUMENT_TYPE = "schematic"
SCHEMATIC_ONLY_FIELDS = ("major_components", "nets", "interfaces")


def metadata_from_dict(data: dict[str, Any]) -> Metadata:
    """Build :class:`Metadata` from a JSON sidecar mapping.

    Args:
        data: Parsed metadata JSON object.

    Returns:
        Metadata instance with defaults for missing optional fields.
    """
    return Metadata(
        project=str(data.get("project", "")),
        build=str(data.get("build", "")),
        document_type=str(data.get("document_type", "")),
        title=str(data.get("title", "")),
        source_file=str(data.get("source_file", "")),
        target_file=str(data.get("target_file", "")),
        source_mtime=float(data.get("source_mtime", 0.0)),
        source_size=int(data.get("source_size", 0)),
        page=int(data.get("page", 0)),
        major_components=data.get("major_components"),
        nets=data.get("nets"),
        interfaces=data.get("interfaces"),
        keywords=list(data.get("keywords", [])),
        version=str(data.get("version", "")),
    )


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


def chunk_to_dict(chunk: Chunk) -> dict[str, Any]:
    """Convert :class:`Chunk` to a JSON-serializable mapping."""
    return {
        "chunk_id": chunk.chunk_id,
        "content": chunk.content,
        "metadata": metadata_to_dict(chunk.metadata),
        "citation": {
            "source_file": chunk.citation.source_file,
            "chunk_id": chunk.citation.chunk_id,
            "page": chunk.citation.page,
            "excerpt": chunk.citation.excerpt,
        },
    }


def chunk_from_dict(data: dict[str, Any]) -> Chunk:
    """Build :class:`Chunk` from a persisted mapping."""
    citation_data = data.get("citation", {})
    return Chunk(
        chunk_id=str(data["chunk_id"]),
        content=str(data["content"]),
        metadata=metadata_from_dict(data.get("metadata", {})),
        citation=Citation(
            source_file=str(citation_data.get("source_file", "")),
            chunk_id=str(citation_data.get("chunk_id", data.get("chunk_id", ""))),
            page=int(citation_data.get("page", 0)),
            excerpt=str(citation_data.get("excerpt", "")),
        ),
    )
