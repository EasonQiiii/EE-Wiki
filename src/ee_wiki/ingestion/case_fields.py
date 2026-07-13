"""Extract structured debug-case fields from failure-analysis documents.

Authors may supply fields via YAML frontmatter and/or Markdown headings under
``fa/`` documents. Existing sidecar values win over heuristics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import FAILURE_ANALYSIS_DOCUMENT_TYPE
from ee_wiki.common.types import Metadata, StandardDocument
from ee_wiki.ingestion.keywords import is_designator, is_part_number_keyword

logger = get_logger(__name__)

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z",
    re.DOTALL,
)
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s+(.+)$", re.MULTILINE)
_COMMA_SPLIT_RE = re.compile(r"[,;/|]+")
_RMA_ID_RE = re.compile(
    r"\b(RMA|NCR|CAR)[\s\-#:]*([A-Z0-9][A-Z0-9\-_/]{2,})\b",
    re.IGNORECASE,
)

_SYMPTOM_HEADINGS = frozenset(
    {"symptom", "symptoms", "failure symptom", "observed symptom", "issue"}
)
_NET_HEADINGS = frozenset(
    {"suspected nets", "suspected net", "nets", "affected nets", "related nets"}
)
_PART_HEADINGS = frozenset(
    {
        "suspected parts",
        "suspected part",
        "suspected components",
        "suspected component",
        "parts",
        "components",
        "affected parts",
    }
)
_STEPS_HEADINGS = frozenset(
    {
        "steps",
        "debug steps",
        "investigation steps",
        "procedure",
        "actions",
        "troubleshooting steps",
    }
)
_ROOT_CAUSE_HEADINGS = frozenset(
    {"root cause", "rootcause", "cause", "conclusion", "finding"}
)
_CASE_ID_HEADINGS = frozenset({"case id", "case_id", "rma", "rma id", "ncr"})
_CITATION_HEADINGS = frozenset(
    {"citations", "references", "see also", "related documents", "case citations"}
)

_FRONTMATTER_KEYS = {
    "case_id": "case_id",
    "caseid": "case_id",
    "id": "case_id",
    "symptom": "symptom",
    "symptoms": "symptom",
    "suspected_nets": "suspected_nets",
    "suspected_net": "suspected_nets",
    "nets": "suspected_nets",
    "suspected_parts": "suspected_parts",
    "suspected_part": "suspected_parts",
    "suspected_components": "suspected_parts",
    "parts": "suspected_parts",
    "components": "suspected_parts",
    "steps": "steps",
    "debug_steps": "steps",
    "root_cause": "root_cause",
    "rootcause": "root_cause",
    "cause": "root_cause",
    "citations": "case_citations",
    "case_citations": "case_citations",
    "references": "case_citations",
}


@dataclass(frozen=True)
class CaseFields:
    """Structured debug-case fields extracted from an FA document."""

    case_id: str | None = None
    symptom: str | None = None
    suspected_nets: tuple[str, ...] = ()
    suspected_parts: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    root_cause: str | None = None
    case_citations: tuple[str, ...] = ()
    body: str | None = None

    def has_structured_fields(self) -> bool:
        """Return whether any authoring field beyond optional body was found."""
        return bool(
            self.case_id
            or self.symptom
            or self.suspected_nets
            or self.suspected_parts
            or self.steps
            or self.root_cause
            or self.case_citations
        )


def _normalize_heading(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s_]+", " ", text.strip().lower())
    return " ".join(cleaned.replace("_", " ").split())


def _as_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p.strip() for p in _COMMA_SPLIT_RE.split(value) if p.strip()]
        if parts:
            return parts
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def _as_optional_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(parts) if parts else None
    text = str(value).strip()
    return text or None


def split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split optional YAML frontmatter from a Markdown body.

    Args:
        content: Raw Markdown text, optionally starting with ``---`` YAML.

    Returns:
        ``(frontmatter_mapping, body)``. Body is unchanged when no frontmatter
        is present.
    """
    if not content.lstrip().startswith("---"):
        return {}, content
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    raw_yaml, body = match.group(1), match.group(2)
    try:
        parsed = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError as exc:
        logger.warning("Ignoring invalid case frontmatter: %s", exc)
        return {}, content
    if not isinstance(parsed, dict):
        logger.warning("Ignoring non-mapping case frontmatter")
        return {}, content
    return dict(parsed), body if body.endswith("\n") else body + "\n"


def _fields_from_frontmatter(data: dict[str, Any]) -> CaseFields:
    mapped: dict[str, Any] = {}
    for key, value in data.items():
        target = _FRONTMATTER_KEYS.get(str(key).strip().lower())
        if target is None:
            continue
        mapped[target] = value
    return CaseFields(
        case_id=_as_optional_string(mapped.get("case_id")),
        symptom=_as_optional_string(mapped.get("symptom")),
        suspected_nets=tuple(_as_string_list(mapped.get("suspected_nets"))),
        suspected_parts=tuple(_as_string_list(mapped.get("suspected_parts"))),
        steps=tuple(_as_string_list(mapped.get("steps"))),
        root_cause=_as_optional_string(mapped.get("root_cause")),
        case_citations=tuple(_as_string_list(mapped.get("case_citations"))),
    )


def _section_map(content: str) -> dict[str, str]:
    matches = list(_HEADING_RE.finditer(content))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = _normalize_heading(match.group(2))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        if title and body:
            sections[title] = body
    return sections


def _paragraph_or_list(body: str) -> list[str]:
    items = [m.group(1).strip() for m in _LIST_ITEM_RE.finditer(body)]
    if items:
        return items
    text = " ".join(line.strip() for line in body.splitlines() if line.strip())
    return [text] if text else []


def _tokens_from_section(body: str) -> list[str]:
    items = _paragraph_or_list(body)
    tokens: list[str] = []
    for item in items:
        tokens.extend(_as_string_list(item))
    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        key = token.upper()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(token)
    return ordered


def _fields_from_headings(content: str) -> CaseFields:
    sections = _section_map(content)
    case_id: str | None = None
    symptom: str | None = None
    suspected_nets: list[str] = []
    suspected_parts: list[str] = []
    steps: list[str] = []
    root_cause: str | None = None
    citations: list[str] = []

    for title, body in sections.items():
        if title in _CASE_ID_HEADINGS and not case_id:
            case_id = _as_optional_string(body.splitlines()[0] if body else None)
        elif title in _SYMPTOM_HEADINGS and not symptom:
            parts = _paragraph_or_list(body)
            symptom = " ".join(parts) if parts else None
        elif title in _NET_HEADINGS:
            suspected_nets.extend(_tokens_from_section(body))
        elif title in _PART_HEADINGS:
            suspected_parts.extend(_tokens_from_section(body))
        elif title in _STEPS_HEADINGS:
            steps.extend(_paragraph_or_list(body))
        elif title in _ROOT_CAUSE_HEADINGS and not root_cause:
            parts = _paragraph_or_list(body)
            root_cause = " ".join(parts) if parts else None
        elif title in _CITATION_HEADINGS:
            citations.extend(_tokens_from_section(body))

    return CaseFields(
        case_id=case_id,
        symptom=symptom,
        suspected_nets=tuple(suspected_nets),
        suspected_parts=tuple(suspected_parts),
        steps=tuple(steps),
        root_cause=root_cause,
        case_citations=tuple(citations),
    )


def _prefer(existing: str | None, extracted: str | None) -> str | None:
    if existing and existing.strip():
        return existing.strip()
    if extracted and extracted.strip():
        return extracted.strip()
    return None


def _prefer_list(
    existing: list[str] | None,
    extracted: tuple[str, ...],
) -> list[str] | None:
    if existing:
        return list(existing)
    if extracted:
        return list(extracted)
    return None


def _default_case_id(*, metadata: Metadata, content: str) -> str | None:
    if metadata.case_id:
        return metadata.case_id
    match = _RMA_ID_RE.search(content)
    if match:
        return f"{match.group(1).upper()}:{match.group(2).upper()}"
    if metadata.source_file:
        stem = Path(metadata.source_file).stem
        if stem:
            return stem
    return None


def extract_case_fields(content: str) -> CaseFields:
    """Extract case fields from frontmatter and/or structured headings.

    Args:
        content: Markdown body of a failure-analysis document.

    Returns:
        Extracted fields and optionally a body with frontmatter removed.
    """
    frontmatter, body = split_frontmatter(content)
    from_fm = _fields_from_frontmatter(frontmatter) if frontmatter else CaseFields()
    from_headings = _fields_from_headings(body)
    return CaseFields(
        case_id=_prefer(from_fm.case_id, from_headings.case_id),
        symptom=_prefer(from_fm.symptom, from_headings.symptom),
        suspected_nets=from_fm.suspected_nets or from_headings.suspected_nets,
        suspected_parts=from_fm.suspected_parts or from_headings.suspected_parts,
        steps=from_fm.steps or from_headings.steps,
        root_cause=_prefer(from_fm.root_cause, from_headings.root_cause),
        case_citations=from_fm.case_citations or from_headings.case_citations,
        body=body if frontmatter else None,
    )


def merge_case_fields_into_metadata(
    metadata: Metadata,
    fields: CaseFields,
    *,
    content: str,
) -> Metadata:
    """Merge extracted case fields into metadata (existing sidecar values win).

    Args:
        metadata: Current document metadata.
        fields: Extracted case fields.
        content: Document body used for default ``case_id`` heuristics.

    Returns:
        Updated metadata when any case field is present or derivable.
    """
    case_id = _prefer(metadata.case_id, fields.case_id)
    if case_id is None:
        case_id = _default_case_id(metadata=metadata, content=content)

    symptom = _prefer(metadata.symptom, fields.symptom)
    suspected_nets = _prefer_list(metadata.suspected_nets, fields.suspected_nets)
    suspected_parts = _prefer_list(metadata.suspected_parts, fields.suspected_parts)
    steps = _prefer_list(metadata.steps, fields.steps)
    root_cause = _prefer(metadata.root_cause, fields.root_cause)
    case_citations = _prefer_list(metadata.case_citations, fields.case_citations)

    # Promote designator/part-like tokens from keywords when author omitted lists
    if not suspected_parts and metadata.keywords:
        promoted = [
            token
            for token in metadata.keywords
            if is_designator(token) or is_part_number_keyword(token)
        ]
        if promoted:
            suspected_parts = promoted

    if not any(
        [
            case_id,
            symptom,
            suspected_nets,
            suspected_parts,
            steps,
            root_cause,
            case_citations,
        ]
    ):
        return metadata

    return replace(
        metadata,
        case_id=case_id,
        symptom=symptom,
        suspected_nets=suspected_nets,
        suspected_parts=suspected_parts,
        steps=steps,
        root_cause=root_cause,
        case_citations=case_citations,
    )


def enrich_failure_analysis_document(document: StandardDocument) -> StandardDocument:
    """Attach structured debug-case fields for ``failure_analysis`` documents.

    Strips YAML frontmatter from the body when present so indexed text stays clean.

    Args:
        document: Parsed standard document.

    Returns:
        Document with case metadata (and cleaned content when frontmatter existed).
        Non-FA documents are returned unchanged.
    """
    if document.metadata.document_type != FAILURE_ANALYSIS_DOCUMENT_TYPE:
        return document

    fields = extract_case_fields(document.content)
    content = fields.body if fields.body is not None else document.content
    new_meta = merge_case_fields_into_metadata(
        document.metadata,
        fields,
        content=content,
    )
    if new_meta is document.metadata and content == document.content:
        return document
    logger.info(
        "Enriched FA case fields for %s (case_id=%s)",
        document.metadata.source_file,
        new_meta.case_id,
    )
    return StandardDocument(
        content=content,
        metadata=new_meta,
        source_ref=document.source_ref,
    )
