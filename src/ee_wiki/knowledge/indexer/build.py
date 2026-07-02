"""Build hybrid retrieval indexes from processed documents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.types import Chunk
from ee_wiki.knowledge.chunker import chunk_processed_records
from ee_wiki.knowledge.indexer.store import IndexManifest, save_index
from ee_wiki.knowledge.loader import ProcessedRecord, load_processed_records
from ee_wiki.retrieval.tokenizer import tokenize_hw_text

logger = get_logger(__name__)


@dataclass(frozen=True)
class IndexBuildResult:
    """Outcome of an index build run."""

    manifest: IndexManifest
    chunk_count: int


def _record_fingerprints(records: list[ProcessedRecord]) -> dict[str, dict[str, float | int]]:
    return {
        record.target_file: {
            "source_mtime": record.metadata.source_mtime,
            "source_size": record.metadata.source_size,
        }
        for record in records
        if record.target_file
    }


def _resolve_embed_device() -> str:
    """Pick the best available torch device for offline embedding."""
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _encode_embeddings(chunks: list[Chunk], config: AppConfig) -> np.ndarray:
    path = config.models.embedding_model
    if path is None:
        raise RuntimeError("models.embedding_model is not configured")
    from sentence_transformers import SentenceTransformer

    device = _resolve_embed_device()
    logger.info("Loading embedding model from %s (device=%s)", path, device)
    model = SentenceTransformer(str(path), device=device)
    texts = [chunk.content for chunk in chunks]
    logger.info(
        "Embedding %d chunk(s); this may take a few minutes on CPU — progress bar below",
        len(texts),
    )
    started = time.monotonic()
    embeddings = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=True,
        batch_size=8,
    )
    logger.info(
        "Embedding finished in %.1fs (%d vectors, dim=%d)",
        time.monotonic() - started,
        len(texts),
        embeddings.shape[1] if embeddings.ndim == 2 else 0,
    )
    return embeddings


def build_index_from_processed(
    config: AppConfig,
    *,
    embedder: Any | None = None,
) -> IndexBuildResult:
    """Chunk processed documents and persist a hybrid index.

    Args:
        config: Application configuration with processed and indexes paths.
        embedder: Optional callable ``(list[str]) -> np.ndarray`` for tests.

    Returns:
        Build result with manifest and chunk count.

    Raises:
        RuntimeError: When no processed documents exist or embedding model is missing.
    """
    records = load_processed_records(config.processed_dir)
    if not records:
        raise RuntimeError(f"No processed documents found under {config.processed_dir}")

    chunks = chunk_processed_records(records, config.chunking)
    if not chunks:
        raise RuntimeError("Chunking produced zero chunks from processed documents")

    if embedder is not None:
        embeddings = embedder([chunk.content for chunk in chunks])
    else:
        embeddings = _encode_embeddings(chunks, config)

    logger.info("Tokenizing %d chunk(s) for BM25", len(chunks))
    started = time.monotonic()
    bm25_corpus = [tokenize_hw_text(chunk.content) for chunk in chunks]
    logger.info("BM25 tokenization finished in %.1fs", time.monotonic() - started)

    logger.info("Writing index to %s", config.indexes_dir)
    manifest = save_index(
        config.indexes_dir,
        chunks=chunks,
        embeddings=embeddings,
        bm25_corpus=bm25_corpus,
        source_fingerprints=_record_fingerprints(records),
    )
    return IndexBuildResult(manifest=manifest, chunk_count=len(chunks))
