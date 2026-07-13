"""Serialize core types for persistence."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from ee_wiki.common.types import Chunk, Citation, Metadata, PageMetadata

SCHEMATIC_DOCUMENT_TYPE = "schematic"
DATASHEET_DOCUMENT_TYPE = "datasheet"
FAILURE_ANALYSIS_DOCUMENT_TYPE = "failure_analysis"
SCHEMATIC_ONLY_FIELDS = ("major_components", "nets", "pages")
DATASHEET_ONLY_FIELDS = ("supply_voltage", "pin_count", "package")
CASE_ONLY_FIELDS = (
    "case_id",
    "symptom",
    "suspected_nets",
    "suspected_parts",
    "steps",
    "root_cause",
    "case_citations",
)


def _page_metadata_from_dict(data: dict[str, Any]) -> PageMetadata:
    """Build :class:`PageMetadata` from a sidecar page entry."""
    return PageMetadata(
        page=int(data.get("page", 0)),
        major_components=list(data.get("major_components", [])),
        nets=list(data.get("nets", [])),
        interfaces=list(data.get("interfaces", [])),
    )


def _pages_from_dict(data: dict[str, Any]) -> list[PageMetadata] | None:
    """Parse optional per-page schematic metadata from a sidecar mapping."""
    raw_pages = data.get("pages")
    if not isinstance(raw_pages, list) or not raw_pages:
        return None
    return [_page_metadata_from_dict(item) for item in raw_pages if isinstance(item, dict)]


def _pages_to_dict(pages: list[PageMetadata] | None) -> list[dict[str, Any]] | None:
    """Serialize per-page schematic metadata for JSON sidecars."""
    if not pages:
        return None
    return [
        {
            "page": page.page,
            "major_components": page.major_components,
            "nets": page.nets,
            "interfaces": page.interfaces,
        }
        for page in pages
    ]


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
        pages=_pages_from_dict(data),
        keywords=list(data.get("keywords", [])),
        supply_voltage=_optional_string_list(data.get("supply_voltage")),
        pin_count=_optional_int(data.get("pin_count")),
        package=_optional_string(data.get("package")),
        case_id=_optional_string(data.get("case_id")),
        symptom=_optional_string(data.get("symptom")),
        suspected_nets=_optional_string_list(data.get("suspected_nets")),
        suspected_parts=_optional_string_list(data.get("suspected_parts")),
        steps=_optional_string_list(data.get("steps")),
        root_cause=_optional_string(data.get("root_cause")),
        case_citations=_optional_string_list(data.get("case_citations")),
        version=str(data.get("version", "")),
    )


def _optional_string_list(value: object) -> list[str] | None:
    """Parse an optional list of strings from JSON."""
    if not isinstance(value, list) or not value:
        return None
    return [str(item) for item in value]


def _optional_int(value: object) -> int | None:
    """Parse an optional integer from JSON."""
    if value is None:
        return None
    return int(value)


def _optional_string(value: object) -> str | None:
    """Parse an optional string from JSON."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    else:
        pages_payload = _pages_to_dict(metadata.pages)
        if pages_payload is None:
            data.pop("pages", None)
        else:
            data["pages"] = pages_payload

    if metadata.document_type != DATASHEET_DOCUMENT_TYPE:
        for key in DATASHEET_ONLY_FIELDS:
            data.pop(key, None)
    else:
        if not metadata.supply_voltage:
            data.pop("supply_voltage", None)
        if metadata.pin_count is None:
            data.pop("pin_count", None)
        if not metadata.package:
            data.pop("package", None)

    if metadata.document_type != FAILURE_ANALYSIS_DOCUMENT_TYPE:
        for key in CASE_ONLY_FIELDS:
            data.pop(key, None)
    else:
        if not metadata.case_id:
            data.pop("case_id", None)
        if not metadata.symptom:
            data.pop("symptom", None)
        if not metadata.suspected_nets:
            data.pop("suspected_nets", None)
        if not metadata.suspected_parts:
            data.pop("suspected_parts", None)
        if not metadata.steps:
            data.pop("steps", None)
        if not metadata.root_cause:
            data.pop("root_cause", None)
        if not metadata.case_citations:
            data.pop("case_citations", None)

    if metadata.document_type not in (SCHEMATIC_DOCUMENT_TYPE, DATASHEET_DOCUMENT_TYPE):
        data.pop("interfaces", None)
    elif not metadata.interfaces:
        data.pop("interfaces", None)

    if not metadata.target_file:
        data.pop("target_file", None)

    return data


def chunk_to_dict(chunk: Chunk) -> dict[str, Any]:
    """Convert :class:`Chunk` to a JSON-serializable mapping."""
    data: dict[str, Any] = {
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
    if chunk.heading_path:
        data["heading_path"] = chunk.heading_path
    return data


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
        heading_path=str(data.get("heading_path", "")),
    )
