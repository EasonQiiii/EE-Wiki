"""Build and load the debug-case lookup index from failure-analysis chunks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import FAILURE_ANALYSIS_DOCUMENT_TYPE
from ee_wiki.common.types import Chunk

logger = get_logger(__name__)

CASES_NAME = "cases.json"
CASE_INDEX_VERSION = 1


class CaseIndexError(EEWikiError):
    """Failed to read or write the debug-case index."""


@dataclass(frozen=True)
class DebugCaseRecord:
    """One debug / failure-analysis case record."""

    case_id: str
    project: str
    build: str
    title: str
    source_file: str
    document_type: str
    symptom: str = ""
    suspected_nets: tuple[str, ...] = ()
    suspected_parts: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    root_cause: str = ""
    case_citations: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    chunk_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize this case for JSON persistence."""
        payload: dict[str, Any] = {
            "case_id": self.case_id,
            "project": self.project,
            "build": self.build,
            "title": self.title,
            "source_file": self.source_file,
            "document_type": self.document_type,
            "chunk_ids": list(self.chunk_ids),
        }
        if self.symptom:
            payload["symptom"] = self.symptom
        if self.suspected_nets:
            payload["suspected_nets"] = list(self.suspected_nets)
        if self.suspected_parts:
            payload["suspected_parts"] = list(self.suspected_parts)
        if self.steps:
            payload["steps"] = list(self.steps)
        if self.root_cause:
            payload["root_cause"] = self.root_cause
        if self.case_citations:
            payload["case_citations"] = list(self.case_citations)
        if self.keywords:
            payload["keywords"] = list(self.keywords)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebugCaseRecord:
        """Deserialize a case record from a JSON object."""
        return cls(
            case_id=str(data.get("case_id", "")),
            project=str(data.get("project", "")),
            build=str(data.get("build", "")),
            title=str(data.get("title", "")),
            source_file=str(data.get("source_file", "")),
            document_type=str(
                data.get("document_type", FAILURE_ANALYSIS_DOCUMENT_TYPE)
            ),
            symptom=str(data.get("symptom", "")),
            suspected_nets=tuple(
                str(item) for item in data.get("suspected_nets", []) if str(item).strip()
            ),
            suspected_parts=tuple(
                str(item)
                for item in data.get("suspected_parts", [])
                if str(item).strip()
            ),
            steps=tuple(str(item) for item in data.get("steps", []) if str(item).strip()),
            root_cause=str(data.get("root_cause", "")),
            case_citations=tuple(
                str(item)
                for item in data.get("case_citations", [])
                if str(item).strip()
            ),
            keywords=tuple(
                str(item) for item in data.get("keywords", []) if str(item).strip()
            ),
            chunk_ids=tuple(
                str(item) for item in data.get("chunk_ids", []) if str(item).strip()
            ),
        )

    def searchable_text(self) -> str:
        """Return a single uppercase haystack for token matching."""
        parts = [
            self.case_id,
            self.title,
            self.symptom,
            self.root_cause,
            " ".join(self.suspected_nets),
            " ".join(self.suspected_parts),
            " ".join(self.steps),
            " ".join(self.keywords),
            " ".join(self.case_citations),
            self.source_file,
        ]
        return " ".join(parts).upper()


@dataclass(frozen=True)
class CaseIndex:
    """Collection of debug-case records keyed by ``case_id`` (may collide across scope)."""

    version: int
    built_at: str
    cases: tuple[DebugCaseRecord, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the case index for JSON persistence."""
        return {
            "version": self.version,
            "built_at": self.built_at,
            "cases": [case.to_dict() for case in self.cases],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaseIndex:
        """Deserialize a case index from a JSON object."""
        raw_cases = data.get("cases", [])
        cases: list[DebugCaseRecord] = []
        if isinstance(raw_cases, list):
            for item in raw_cases:
                if isinstance(item, dict):
                    cases.append(DebugCaseRecord.from_dict(item))
        return cls(
            version=int(data.get("version", 0)),
            built_at=str(data.get("built_at", "")),
            cases=tuple(cases),
        )


def case_index_path(indexes_dir: Path) -> Path:
    """Return the on-disk path for the debug-case lookup index."""
    return indexes_dir.resolve() / CASES_NAME


def _chunk_has_case_signal(chunk: Chunk) -> bool:
    meta = chunk.metadata
    return bool(
        meta.case_id
        or meta.symptom
        or meta.root_cause
        or meta.suspected_nets
        or meta.suspected_parts
        or meta.steps
        or meta.case_citations
    )


def build_case_index(chunks: list[Chunk]) -> CaseIndex:
    """Build a debug-case index from indexed failure-analysis chunks.

    One record is emitted per ``source_file``. Structured metadata fields on the
    first matching chunk win; ``chunk_ids`` accumulate all chunks for that file.

    Args:
        chunks: Indexed retrieval chunks.

    Returns:
        Case index containing FA documents with case signals.
    """
    by_source: dict[str, dict[str, Any]] = {}

    for chunk in chunks:
        meta = chunk.metadata
        if meta.document_type != FAILURE_ANALYSIS_DOCUMENT_TYPE:
            continue
        if not meta.source_file or not _chunk_has_case_signal(chunk):
            continue

        entry = by_source.get(meta.source_file)
        if entry is None:
            case_id = (meta.case_id or Path(meta.source_file).stem or chunk.chunk_id).strip()
            by_source[meta.source_file] = {
                "case_id": case_id,
                "project": meta.project,
                "build": meta.build,
                "title": meta.title,
                "source_file": meta.source_file,
                "document_type": meta.document_type,
                "symptom": meta.symptom or "",
                "suspected_nets": list(meta.suspected_nets or []),
                "suspected_parts": list(meta.suspected_parts or []),
                "steps": list(meta.steps or []),
                "root_cause": meta.root_cause or "",
                "case_citations": list(meta.case_citations or []),
                "keywords": list(meta.keywords or []),
                "chunk_ids": [chunk.chunk_id],
            }
            continue

        if chunk.chunk_id not in entry["chunk_ids"]:
            entry["chunk_ids"].append(chunk.chunk_id)
        if not entry["symptom"] and meta.symptom:
            entry["symptom"] = meta.symptom
        if not entry["root_cause"] and meta.root_cause:
            entry["root_cause"] = meta.root_cause
        if not entry["suspected_nets"] and meta.suspected_nets:
            entry["suspected_nets"] = list(meta.suspected_nets)
        if not entry["suspected_parts"] and meta.suspected_parts:
            entry["suspected_parts"] = list(meta.suspected_parts)
        if not entry["steps"] and meta.steps:
            entry["steps"] = list(meta.steps)
        if not entry["case_citations"] and meta.case_citations:
            entry["case_citations"] = list(meta.case_citations)
        if meta.keywords:
            merged = list(dict.fromkeys([*entry["keywords"], *meta.keywords]))
            entry["keywords"] = merged

    cases = tuple(
        DebugCaseRecord(
            case_id=str(item["case_id"]),
            project=str(item["project"]),
            build=str(item["build"]),
            title=str(item["title"]),
            source_file=str(item["source_file"]),
            document_type=str(item["document_type"]),
            symptom=str(item["symptom"]),
            suspected_nets=tuple(item["suspected_nets"]),
            suspected_parts=tuple(item["suspected_parts"]),
            steps=tuple(item["steps"]),
            root_cause=str(item["root_cause"]),
            case_citations=tuple(item["case_citations"]),
            keywords=tuple(item["keywords"]),
            chunk_ids=tuple(item["chunk_ids"]),
        )
        for item in sorted(
            by_source.values(),
            key=lambda row: (row["project"], row["build"], row["case_id"]),
        )
    )
    built_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    logger.info("Built case index with %d case(s) from %d chunk(s)", len(cases), len(chunks))
    return CaseIndex(version=CASE_INDEX_VERSION, built_at=built_at, cases=cases)


def save_case_index(chunks: list[Chunk], indexes_dir: Path) -> CaseIndex:
    """Persist the debug-case index alongside the hybrid index bundle.

    Args:
        chunks: Indexed retrieval chunks.
        indexes_dir: Directory containing the hybrid index bundle.

    Returns:
        Saved case index.

    Raises:
        CaseIndexError: If writing the index file fails.
    """
    index = build_case_index(chunks)
    path = case_index_path(indexes_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(index.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise CaseIndexError(f"Failed to write case index: {path}") from exc
    logger.info("Wrote case index to %s", path)
    return index


def load_case_index(indexes_dir: Path) -> CaseIndex | None:
    """Load the debug-case index when present.

    Args:
        indexes_dir: Directory containing the hybrid index bundle.

    Returns:
        Loaded case index, or ``None`` when the file is missing.
    """
    path = case_index_path(indexes_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CaseIndexError(f"Failed to read case index: {path}") from exc
    return CaseIndex.from_dict(data)


def clear_case_index(indexes_dir: Path) -> None:
    """Remove the debug-case index file if it exists."""
    path = case_index_path(indexes_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise CaseIndexError(f"Failed to remove case index: {path}") from exc
