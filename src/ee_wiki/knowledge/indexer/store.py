"""Persist and load hybrid retrieval indexes on disk."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from ee_wiki.common.errors import EEWikiError
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import chunk_from_dict, chunk_to_dict
from ee_wiki.common.types import Chunk
from ee_wiki.knowledge.indexer.component_index import clear_component_index

logger = get_logger(__name__)

INDEX_VERSION = 1
MANIFEST_NAME = "manifest.json"
CHUNKS_NAME = "chunks.jsonl"
EMBEDDINGS_NAME = "embeddings.npz"
BM25_NAME = "bm25_corpus.json"


class IndexStoreError(EEWikiError):
    """Failed to read or write a persisted index."""


@dataclass(frozen=True)
class IndexManifest:
    """Metadata describing a built on-disk index."""

    version: int
    built_at: str
    chunk_count: int
    source_fingerprints: dict[str, dict[str, float | int]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "built_at": self.built_at,
            "chunk_count": self.chunk_count,
            "source_fingerprints": self.source_fingerprints,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndexManifest:
        return cls(
            version=int(data.get("version", 0)),
            built_at=str(data.get("built_at", "")),
            chunk_count=int(data.get("chunk_count", 0)),
            source_fingerprints=dict(data.get("source_fingerprints", {})),
        )


@dataclass(frozen=True)
class PersistedIndex:
    """Loaded index bundle for hybrid retrieval."""

    manifest: IndexManifest
    chunks: list[Chunk]
    embeddings: np.ndarray
    bm25_corpus: list[list[str]]


def index_paths(indexes_dir: Path) -> dict[str, Path]:
    """Return canonical file paths under ``data/indexes/``."""
    root = indexes_dir.resolve()
    return {
        "manifest": root / MANIFEST_NAME,
        "chunks": root / CHUNKS_NAME,
        "embeddings": root / EMBEDDINGS_NAME,
        "bm25": root / BM25_NAME,
    }


def index_exists(indexes_dir: Path) -> bool:
    """Return whether a complete index bundle exists."""
    paths = index_paths(indexes_dir)
    return all(path.is_file() for path in paths.values())


def clear_index(indexes_dir: Path) -> int:
    """Remove all on-disk index artifacts under ``indexes_dir``.

    Args:
        indexes_dir: Directory containing a previously built index bundle.

    Returns:
        Number of source documents recorded in the manifest before removal,
        or ``0`` when no index existed.
    """
    if not index_exists(indexes_dir):
        return 0

    removed_documents = 0
    try:
        manifest = IndexManifest.from_dict(
            json.loads(index_paths(indexes_dir)["manifest"].read_text(encoding="utf-8"))
        )
        removed_documents = len(manifest.source_fingerprints)
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        logger.warning("Could not read manifest before clearing index at %s", indexes_dir)

    for path in index_paths(indexes_dir).values():
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise IndexStoreError(f"Failed to remove index file {path}") from exc
    clear_component_index(indexes_dir)

    logger.info(
        "Cleared index at %s (%d source document(s) removed)",
        indexes_dir,
        removed_documents,
    )
    return removed_documents


def save_index(
    indexes_dir: Path,
    *,
    chunks: list[Chunk],
    embeddings: np.ndarray,
    bm25_corpus: list[list[str]],
    source_fingerprints: dict[str, dict[str, float | int]],
) -> IndexManifest:
    """Write chunks, embeddings, and BM25 corpus to ``indexes_dir``.

    Args:
        indexes_dir: Target directory (created when missing).
        chunks: Indexed chunks in embedding row order.
        embeddings: ``(n_chunks, dim)`` embedding matrix aligned with ``chunks``.
        bm25_corpus: Tokenized corpus aligned with ``chunks``.
        source_fingerprints: Processed document fingerprints keyed by ``target_file``.

    Returns:
        Written manifest metadata.

    Raises:
        IndexStoreError: If chunk/embedding counts diverge or write fails.
    """
    if len(chunks) != embeddings.shape[0]:
        raise IndexStoreError(
            f"Chunk count ({len(chunks)}) does not match embeddings rows ({embeddings.shape[0]})"
        )
    if len(chunks) != len(bm25_corpus):
        raise IndexStoreError(
            f"Chunk count ({len(chunks)}) does not match BM25 corpus ({len(bm25_corpus)})"
        )

    indexes_dir.mkdir(parents=True, exist_ok=True)
    paths = index_paths(indexes_dir)
    manifest = IndexManifest(
        version=INDEX_VERSION,
        built_at=datetime.now(UTC).isoformat(),
        chunk_count=len(chunks),
        source_fingerprints=source_fingerprints,
    )

    try:
        paths["manifest"].write_text(
            json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        with paths["chunks"].open("w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(json.dumps(chunk_to_dict(chunk), ensure_ascii=False) + "\n")
        np.savez_compressed(
            paths["embeddings"],
            chunk_ids=np.array([chunk.chunk_id for chunk in chunks], dtype=object),
            embeddings=embeddings,
        )
        paths["bm25"].write_text(
            json.dumps(bm25_corpus, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise IndexStoreError(f"Failed to write index under {indexes_dir}") from exc

    logger.info("Wrote index with %d chunk(s) to %s", len(chunks), indexes_dir)
    return manifest


def load_index(indexes_dir: Path) -> PersistedIndex:
    """Load a persisted hybrid index bundle.

    Args:
        indexes_dir: Directory containing manifest, chunks, embeddings, and BM25 files.

    Returns:
        Parsed index ready for retrieval.

    Raises:
        IndexStoreError: If required files are missing or corrupt.
    """
    paths = index_paths(indexes_dir)
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise IndexStoreError(
            f"Index incomplete under {indexes_dir}, missing: {', '.join(missing)}"
        )

    try:
        manifest = IndexManifest.from_dict(
            json.loads(paths["manifest"].read_text(encoding="utf-8"))
        )
        chunks: list[Chunk] = []
        with paths["chunks"].open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    chunks.append(chunk_from_dict(json.loads(line)))
        archive = np.load(paths["embeddings"], allow_pickle=True)
        embeddings = archive["embeddings"]
        bm25_corpus = json.loads(paths["bm25"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise IndexStoreError(f"Failed to load index from {indexes_dir}") from exc

    if manifest.chunk_count != len(chunks):
        raise IndexStoreError(
            f"Manifest chunk_count={manifest.chunk_count} but loaded {len(chunks)} chunks"
        )
    if embeddings.shape[0] != len(chunks):
        raise IndexStoreError("Embeddings row count does not match chunk count")
    if len(bm25_corpus) != len(chunks):
        raise IndexStoreError("BM25 corpus length does not match chunk count")

    logger.info("Loaded index with %d chunk(s) from %s", len(chunks), indexes_dir)
    return PersistedIndex(
        manifest=manifest,
        chunks=chunks,
        embeddings=embeddings,
        bm25_corpus=bm25_corpus,
    )
