"""Build and load the lightweight component lookup index."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE
from ee_wiki.common.types import Chunk
from ee_wiki.ingestion.keywords import is_designator, is_part_number_keyword

logger = get_logger(__name__)

COMPONENTS_NAME = "components.json"
COMPONENT_INDEX_VERSION = 1
ComponentKind = Literal["designator", "part_number"]


class ComponentIndexError(EEWikiError):
    """Failed to read or write the component index."""


@dataclass(frozen=True)
class ComponentHit:
    """One chunk reference for a component key."""

    key: str
    kind: ComponentKind
    chunk_id: str
    project: str
    build: str
    document_type: str
    source_file: str
    page: int
    title: str
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "chunk_id": self.chunk_id,
            "project": self.project,
            "build": self.build,
            "document_type": self.document_type,
            "source_file": self.source_file,
            "page": self.page,
            "title": self.title,
            "excerpt": self.excerpt,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentHit:
        return cls(
            key=str(data.get("key", "")),
            kind=str(data.get("kind", "part_number")),  # type: ignore[arg-type]
            chunk_id=str(data.get("chunk_id", "")),
            project=str(data.get("project", "")),
            build=str(data.get("build", "")),
            document_type=str(data.get("document_type", "")),
            source_file=str(data.get("source_file", "")),
            page=int(data.get("page", 0)),
            title=str(data.get("title", "")),
            excerpt=str(data.get("excerpt", "")),
        )


@dataclass(frozen=True)
class ComponentIndex:
    """Inverted index mapping component keys to chunk references."""

    version: int
    built_at: str
    entries: dict[str, list[ComponentHit]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "built_at": self.built_at,
            "entries": {
                key: [hit.to_dict() for hit in hits]
                for key, hits in sorted(self.entries.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComponentIndex:
        raw_entries = data.get("entries", {})
        entries: dict[str, list[ComponentHit]] = {}
        if isinstance(raw_entries, dict):
            for key, hits in raw_entries.items():
                if not isinstance(hits, list):
                    continue
                entries[str(key).upper()] = [
                    ComponentHit.from_dict(item)
                    for item in hits
                    if isinstance(item, dict)
                ]
        return cls(
            version=int(data.get("version", 0)),
            built_at=str(data.get("built_at", "")),
            entries=entries,
        )


def component_index_path(indexes_dir: Path) -> Path:
    """Return the on-disk path for the component lookup index."""
    return indexes_dir.resolve() / COMPONENTS_NAME


def _normalize_key(token: str) -> str:
    return token.strip().upper()


def _hit_from_chunk(
    chunk: Chunk,
    *,
    key: str,
    kind: ComponentKind,
) -> ComponentHit:
    metadata = chunk.metadata
    return ComponentHit(
        key=key,
        kind=kind,
        chunk_id=chunk.chunk_id,
        project=metadata.project,
        build=metadata.build,
        document_type=metadata.document_type,
        source_file=metadata.source_file,
        page=chunk.citation.page or metadata.page,
        title=metadata.title,
        excerpt=chunk.citation.excerpt,
    )


def build_component_index(chunks: list[Chunk]) -> ComponentIndex:
    """Build a component lookup index from indexed chunks.

    Args:
        chunks: Indexed retrieval chunks.

    Returns:
        Component index with deduplicated ``(key, chunk_id)`` entries.
    """
    entries: dict[str, list[ComponentHit]] = {}
    seen: set[tuple[str, str]] = set()

    def add_hit(chunk: Chunk, token: str, kind: ComponentKind) -> None:
        key = _normalize_key(token)
        if not key:
            return
        dedupe_key = (key, chunk.chunk_id)
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
        entries.setdefault(key, []).append(_hit_from_chunk(chunk, key=key, kind=kind))

    for chunk in chunks:
        metadata = chunk.metadata
        if metadata.document_type == SCHEMATIC_DOCUMENT_TYPE and metadata.major_components:
            for token in metadata.major_components:
                if is_designator(token):
                    add_hit(chunk, token, "designator")

        for token in metadata.keywords:
            if is_part_number_keyword(token):
                add_hit(chunk, token, "part_number")

    built_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    logger.info("Built component index with %d key(s) from %d chunk(s)", len(entries), len(chunks))
    return ComponentIndex(
        version=COMPONENT_INDEX_VERSION,
        built_at=built_at,
        entries=entries,
    )


def save_component_index(chunks: list[Chunk], indexes_dir: Path) -> ComponentIndex:
    """Persist the component lookup index alongside the hybrid index bundle.

    Args:
        chunks: Indexed retrieval chunks.
        indexes_dir: Directory containing the hybrid index bundle.

    Returns:
        Saved component index.

    Raises:
        ComponentIndexError: If writing the index file fails.
    """
    index = build_component_index(chunks)
    path = component_index_path(indexes_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(index.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise ComponentIndexError(f"Failed to write component index: {path}") from exc
    logger.info("Wrote component index to %s", path)
    return index


def load_component_index(indexes_dir: Path) -> ComponentIndex | None:
    """Load the component lookup index when present.

    Args:
        indexes_dir: Directory containing the hybrid index bundle.

    Returns:
        Loaded component index, or ``None`` when the file is missing.
    """
    path = component_index_path(indexes_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComponentIndexError(f"Failed to read component index: {path}") from exc
    return ComponentIndex.from_dict(data)


def clear_component_index(indexes_dir: Path) -> None:
    """Remove the component lookup index file if it exists."""
    path = component_index_path(indexes_dir)
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise ComponentIndexError(f"Failed to remove component index: {path}") from exc
