"""Incremental index sync using processed document fingerprints."""

from __future__ import annotations

from ee_wiki.common.logging import get_logger
from ee_wiki.knowledge.indexer.store import IndexManifest, PersistedIndex
from ee_wiki.knowledge.loader import ProcessedRecord

logger = get_logger(__name__)


def record_fingerprint(record: ProcessedRecord) -> dict[str, float | int]:
    """Return fingerprint fields stored in the index manifest."""
    return {
        "source_mtime": record.metadata.source_mtime,
        "source_size": record.metadata.source_size,
    }


def fingerprints_match(
    stored: dict[str, float | int] | None,
    record: ProcessedRecord,
) -> bool:
    """Return whether ``stored`` matches the processed record fingerprint."""
    if stored is None:
        return False
    current = record_fingerprint(record)
    recorded_mtime = stored.get("source_mtime")
    recorded_size = stored.get("source_size")
    if recorded_mtime is None or recorded_size is None:
        return False
    return (
        float(recorded_mtime) == float(current["source_mtime"])
        and int(recorded_size) == int(current["source_size"])
    )


def plan_index_update(
    records: list[ProcessedRecord],
    manifest: IndexManifest | None,
    *,
    force: bool = False,
) -> tuple[list[ProcessedRecord], set[str], set[str]]:
    """Decide which processed documents require re-indexing.

    Args:
        records: Current processed mirror documents.
        manifest: Existing index manifest, if any.
        force: When ``True``, treat every document as changed.

    Returns:
        Tuple of ``(records_to_index, unchanged_target_files, removed_target_files)``.
    """
    current_targets = {record.target_file for record in records if record.target_file}
    if force or manifest is None:
        removed = (
            set(manifest.source_fingerprints.keys()) - current_targets if manifest else set()
        )
        return records, set(), removed

    stored = manifest.source_fingerprints
    unchanged: set[str] = set()
    to_index: list[ProcessedRecord] = []
    for record in records:
        if not record.target_file:
            to_index.append(record)
            continue
        if fingerprints_match(stored.get(record.target_file), record):
            unchanged.add(record.target_file)
            logger.debug("Skip unchanged index source: %s", record.target_file)
        else:
            to_index.append(record)

    removed = set(stored.keys()) - current_targets
    return to_index, unchanged, removed


def chunks_for_target_file(index: PersistedIndex, target_file: str) -> list:
    """Return chunks belonging to one processed document."""
    return [chunk for chunk in index.chunks if chunk.metadata.target_file == target_file]
