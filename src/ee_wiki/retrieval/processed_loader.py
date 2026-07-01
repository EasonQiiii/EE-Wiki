"""Load processed documents for hybrid retrieval indexing."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import Metadata

logger = get_logger(__name__)


@dataclass(frozen=True)
class ProcessedRecord:
    """One processed document block loaded from ``data/processed/``."""

    chunk_id: str
    content: str
    metadata: Metadata
    target_file: str


def _metadata_from_dict(data: dict[str, Any]) -> Metadata:
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


def load_processed_records(processed_dir: Path) -> list[ProcessedRecord]:
    """Scan ``data/processed/`` for ``*.md`` files and sidecar metadata.

    Args:
        processed_dir: Root of the processed mirror.

    Returns:
        Loaded records ready for chunk indexing.
    """
    if not processed_dir.is_dir():
        logger.warning("Processed dir does not exist: %s", processed_dir)
        return []

    records: list[ProcessedRecord] = []
    for md_path in sorted(processed_dir.rglob("*.md")):
        if md_path.name.endswith(".meta.json"):
            continue
        meta_path = md_path.with_suffix(f"{md_path.suffix}.meta.json")
        meta_data: dict[str, Any] = {}
        if meta_path.is_file():
            meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
        else:
            logger.warning("Missing metadata sidecar for %s", md_path)

        content = md_path.read_text(encoding="utf-8")
        metadata = _metadata_from_dict(meta_data)
        chunk_id = md_path.stem
        target_file = metadata.target_file or str(
            md_path.relative_to(processed_dir.parent)
            if processed_dir.name == "processed"
            else md_path
        )
        records.append(
            ProcessedRecord(
                chunk_id=chunk_id,
                content=content,
                metadata=metadata,
                target_file=target_file,
            )
        )

    logger.info("Loaded %d processed record(s) from %s", len(records), processed_dir)
    return records
