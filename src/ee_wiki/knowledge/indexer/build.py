"""Build hybrid retrieval indexes from processed documents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.ml_device import (
    embedding_batch_size,
    is_mps_embedding_runtime_error,
    resolve_torch_device,
)
from ee_wiki.common.types import Chunk
from ee_wiki.knowledge.chunker import (
    chunk_index_text,
    chunk_processed_record,
    chunk_processed_records,
)
from ee_wiki.knowledge.indexer.case_index import save_case_index
from ee_wiki.knowledge.indexer.component_index import save_component_index
from ee_wiki.knowledge.indexer.store import (
    IndexManifest,
    PersistedIndex,
    clear_index,
    index_exists,
    load_index,
    save_index,
)
from ee_wiki.knowledge.indexer.sync import (
    chunks_for_target_file,
    plan_index_update,
    record_fingerprint,
)
from ee_wiki.knowledge.loader import ProcessedRecord, load_processed_records
from ee_wiki.retrieval.tokenizer import tokenize_hw_text

logger = get_logger(__name__)


@dataclass(frozen=True)
class IndexBuildResult:
    """Outcome of an index build run."""

    manifest: IndexManifest
    chunk_count: int
    indexed_documents: int = 0
    skipped_documents: int = 0
    removed_documents: int = 0


def _record_fingerprints(records: list[ProcessedRecord]) -> dict[str, dict[str, float | int]]:
    return {
        record.target_file: record_fingerprint(record)
        for record in records
        if record.target_file
    }


def _encode_on_device(
    chunks: list[Chunk],
    *,
    model_path: str,
    device: str,
    batch_size: int,
) -> np.ndarray:
    """Embed chunk texts on a single torch device."""
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model from %s (device=%s)", model_path, device)
    model = SentenceTransformer(model_path, device=device)
    texts = [chunk_index_text(chunk) for chunk in chunks]
    effective_batch = embedding_batch_size(device, batch_size)
    logger.info(
        "Embedding %d chunk(s) on %s (batch_size=%d)",
        len(texts),
        device,
        effective_batch,
    )
    started = time.monotonic()
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=True,
        batch_size=effective_batch,
    )
    logger.info(
        "Embedding finished in %.1fs (%d vectors, dim=%d)",
        time.monotonic() - started,
        len(texts),
        embeddings.shape[1] if embeddings.ndim == 2 else 0,
    )
    return embeddings


def _encode_embeddings(chunks: list[Chunk], config: AppConfig) -> np.ndarray:
    path = config.models.embedding_model
    if path is None:
        raise RuntimeError("models.embedding_model is not configured")

    primary_device = resolve_torch_device(config.indexing.embed_device)
    devices = [primary_device]
    if primary_device == "mps":
        devices.append("cpu")

    last_error: RuntimeError | None = None
    for device in devices:
        try:
            return _encode_on_device(
                chunks,
                model_path=str(path),
                device=device,
                batch_size=config.indexing.embed_batch_size,
            )
        except RuntimeError as exc:
            if device == "mps" and is_mps_embedding_runtime_error(exc):
                logger.warning(
                    "MPS embedding failed (%s); retrying index build on CPU",
                    exc,
                )
                last_error = exc
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("Embedding failed without a captured error")


def _embed_chunks(
    chunks: list[Chunk],
    config: AppConfig,
    *,
    embedder: Any | None,
) -> np.ndarray:
    if not chunks:
        return np.zeros((0, 0), dtype=np.float32)
    if embedder is not None:
        return embedder([chunk_index_text(chunk) for chunk in chunks])
    return _encode_embeddings(chunks, config)


def _build_bm25_corpus(chunks: list[Chunk]) -> list[list[str]]:
    logger.info("Tokenizing %d chunk(s) for BM25", len(chunks))
    started = time.monotonic()
    bm25_corpus = [tokenize_hw_text(chunk_index_text(chunk)) for chunk in chunks]
    logger.info("BM25 tokenization finished in %.1fs", time.monotonic() - started)
    return bm25_corpus


def _full_build(
    records: list[ProcessedRecord],
    config: AppConfig,
    *,
    embedder: Any | None,
) -> IndexBuildResult:
    chunks = chunk_processed_records(records, config.chunking)
    if not chunks:
        raise RuntimeError("Chunking produced zero chunks from processed documents")

    embeddings = _embed_chunks(chunks, config, embedder=embedder)
    bm25_corpus = _build_bm25_corpus(chunks)

    logger.info("Writing index to %s", config.indexes_dir)
    manifest = save_index(
        config.indexes_dir,
        chunks=chunks,
        embeddings=embeddings,
        bm25_corpus=bm25_corpus,
        source_fingerprints=_record_fingerprints(records),
    )
    save_component_index(chunks, config.indexes_dir)
    save_case_index(chunks, config.indexes_dir)
    return IndexBuildResult(
        manifest=manifest,
        chunk_count=len(chunks),
        indexed_documents=len(records),
        skipped_documents=0,
        removed_documents=0,
    )


def _merge_incremental_index(
    records: list[ProcessedRecord],
    existing: PersistedIndex,
    *,
    unchanged_targets: set[str],
    records_to_index: list[ProcessedRecord],
    config: AppConfig,
    embedder: Any | None,
) -> tuple[list[Chunk], np.ndarray, list[list[str]]]:
    new_chunks_by_target = {
        record.target_file: chunk_processed_record(record, config.chunking)
        for record in records_to_index
        if record.target_file
    }
    existing_chunk_index = {
        chunk.chunk_id: position for position, chunk in enumerate(existing.chunks)
    }

    final_chunks: list[Chunk] = []
    reuse_positions: list[int | None] = []
    for record in records:
        target_file = record.target_file
        if not target_file:
            doc_chunks = chunk_processed_record(record, config.chunking)
        elif target_file in unchanged_targets:
            doc_chunks = chunks_for_target_file(existing, target_file)
        else:
            doc_chunks = new_chunks_by_target[target_file]

        for chunk in doc_chunks:
            final_chunks.append(chunk)
            if target_file in unchanged_targets:
                reuse_positions.append(existing_chunk_index.get(chunk.chunk_id))
            else:
                reuse_positions.append(None)

    chunks_to_embed = [
        final_chunks[index]
        for index, reuse in enumerate(reuse_positions)
        if reuse is None
    ]
    new_embeddings = _embed_chunks(chunks_to_embed, config, embedder=embedder)

    embedding_dim = existing.embeddings.shape[1] if existing.embeddings.size else (
        new_embeddings.shape[1] if new_embeddings.size else 0
    )
    merged_embeddings: list[np.ndarray] = []
    new_cursor = 0
    for reuse in reuse_positions:
        if reuse is not None:
            merged_embeddings.append(existing.embeddings[reuse])
        else:
            merged_embeddings.append(new_embeddings[new_cursor])
            new_cursor += 1

    if merged_embeddings:
        embeddings = np.vstack(merged_embeddings)
    else:
        embeddings = np.zeros((0, embedding_dim), dtype=np.float32)

    bm25_corpus = _build_bm25_corpus(final_chunks)
    return final_chunks, embeddings, bm25_corpus


def build_index_from_processed(
    config: AppConfig,
    *,
    force: bool = False,
    embedder: Any | None = None,
) -> IndexBuildResult:
    """Chunk processed documents and persist a hybrid index.

    When an index already exists and ``force`` is false, only new or changed
    processed documents are re-chunked and re-embedded. Unchanged documents
    reuse existing chunk rows and embeddings. Documents removed from the
    processed mirror are dropped from the index.

    Args:
        config: Application configuration with processed and indexes paths.
        force: When ``True``, rebuild the full index from scratch.
        embedder: Optional callable ``(list[str]) -> np.ndarray`` for tests.

    Returns:
        Build result with manifest, chunk count, and per-run document stats.

    Raises:
        RuntimeError: When no processed documents exist or embedding model is missing.
    """
    records = load_processed_records(config.processed_dir)
    if not records:
        if index_exists(config.indexes_dir):
            removed_documents = clear_index(config.indexes_dir)
            logger.info(
                "No processed documents remain; cleared index (%d document(s) removed)",
                removed_documents,
            )
            return IndexBuildResult(
                manifest=IndexManifest(
                    version=1,
                    built_at="",
                    chunk_count=0,
                    source_fingerprints={},
                ),
                chunk_count=0,
                indexed_documents=0,
                skipped_documents=0,
                removed_documents=removed_documents,
            )
        raise RuntimeError(f"No processed documents found under {config.processed_dir}")

    if force or not index_exists(config.indexes_dir):
        if force:
            logger.info("Force rebuild: indexing all processed documents")
        return _full_build(records, config, embedder=embedder)

    existing = load_index(config.indexes_dir)
    records_to_index, unchanged_targets, removed_targets = plan_index_update(
        records,
        existing.manifest,
        force=False,
    )

    if not records_to_index and not removed_targets:
        logger.info(
            "Index up to date: %d chunk(s), %d document(s) unchanged",
            existing.manifest.chunk_count,
            len(unchanged_targets),
        )
        return IndexBuildResult(
            manifest=existing.manifest,
            chunk_count=existing.manifest.chunk_count,
            indexed_documents=0,
            skipped_documents=len(unchanged_targets),
            removed_documents=0,
        )

    logger.info(
        "Incremental index update: %d document(s) to index, %d unchanged, %d removed",
        len(records_to_index),
        len(unchanged_targets),
        len(removed_targets),
    )
    chunks, embeddings, bm25_corpus = _merge_incremental_index(
        records,
        existing,
        unchanged_targets=unchanged_targets,
        records_to_index=records_to_index,
        config=config,
        embedder=embedder,
    )
    if not chunks:
        raise RuntimeError("Incremental merge produced zero chunks")

    logger.info("Writing index to %s", config.indexes_dir)
    manifest = save_index(
        config.indexes_dir,
        chunks=chunks,
        embeddings=embeddings,
        bm25_corpus=bm25_corpus,
        source_fingerprints=_record_fingerprints(records),
    )
    save_component_index(chunks, config.indexes_dir)
    save_case_index(chunks, config.indexes_dir)
    return IndexBuildResult(
        manifest=manifest,
        chunk_count=len(chunks),
        indexed_documents=len(records_to_index),
        skipped_documents=len(unchanged_targets),
        removed_documents=len(removed_targets),
    )
