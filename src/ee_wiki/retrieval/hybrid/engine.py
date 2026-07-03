"""Offline hybrid retrieval engine (embedding + BM25 + reranker).

Loads persisted chunk indexes from ``data/indexes/`` when available; otherwise
builds from processed documents via :mod:`ee_wiki.knowledge.indexer`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.common.serialization import SCHEMATIC_DOCUMENT_TYPE, metadata_to_dict
from ee_wiki.common.types import Chunk
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope
from ee_wiki.retrieval.metadata_boost import metadata_keyword_boost
from ee_wiki.retrieval.query_boost import query_boost_tokens
from ee_wiki.retrieval.query_expand import expand_hw_query
from ee_wiki.retrieval.query_intent import effective_document_type, prefers_schematic_sources
from ee_wiki.retrieval.rerank_excerpt import query_focused_excerpt
from ee_wiki.retrieval.section_expand import build_section_index, expand_retrieved_sections
from ee_wiki.retrieval.tokenizer import tokenize_hw_text

logger = get_logger(__name__)


@dataclass
class HybridChunk:
    """Indexed chunk with optional embedding vector."""

    chunk_id: str
    content: str
    metadata: dict[str, Any]
    citation: dict[str, Any]
    embedding: np.ndarray | None = None


@dataclass(frozen=True)
class RetrievalResult:
    """Ranked chunks plus the best reranker score from the candidate set."""

    chunks: list[HybridChunk]
    top_rerank_score: float | None = None


def _chunk_to_hybrid(chunk: Chunk, embedding: np.ndarray | None = None) -> HybridChunk:
    return HybridChunk(
        chunk_id=chunk.chunk_id,
        content=chunk.content,
        metadata=metadata_to_dict(chunk.metadata),
        citation={
            "source_file": chunk.citation.source_file,
            "chunk_id": chunk.citation.chunk_id,
            "page": chunk.citation.page,
            "excerpt": chunk.citation.excerpt,
        },
        embedding=embedding,
    )


@dataclass
class HybridRagEngine:
    """Hybrid retrieval over chunked, indexed documents."""

    config: AppConfig
    knowledge_base: list[HybridChunk] = field(default_factory=list)
    bm25: Any | None = None
    _chunk_positions: dict[str, int] = field(default_factory=dict, repr=False)
    _embed_model: Any | None = field(default=None, repr=False)
    _rerank_model: Any | None = field(default=None, repr=False)
    _rerank_tokenizer: Any | None = field(default=None, repr=False)
    _device: str | None = field(default=None, repr=False)
    _model_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _section_index: dict[str, list[HybridChunk]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._device = self._detect_device()

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_embed_model(self) -> None:
        if self._embed_model is not None:
            return
        path = self.config.models.embedding_model
        if path is None:
            raise RuntimeError("models.embedding_model is not configured")
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model from %s", path)
        self._embed_model = SentenceTransformer(str(path), device=str(self._device))

    def _load_reranker(self) -> None:
        if self._rerank_model is not None:
            return
        path = self.config.models.reranker_model
        if path is None:
            raise RuntimeError("models.reranker_model is not configured")
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        logger.info("Loading reranker model from %s", path)
        self._rerank_tokenizer = AutoTokenizer.from_pretrained(str(path))
        self._rerank_model = AutoModelForSequenceClassification.from_pretrained(str(path)).to(
            self._device
        )
        self._rerank_model.eval()

    def _apply_loaded_index(
        self,
        chunks: list[Chunk],
        embeddings: np.ndarray,
        bm25_corpus: list[list[str]],
    ) -> None:
        from rank_bm25 import BM25Okapi

        self.knowledge_base = [
            _chunk_to_hybrid(chunk, embeddings[index])
            for index, chunk in enumerate(chunks)
        ]
        self._chunk_positions = {
            chunk.chunk_id: index for index, chunk in enumerate(self.knowledge_base)
        }
        self.bm25 = BM25Okapi(bm25_corpus) if bm25_corpus else None
        self._section_index = build_section_index(self.knowledge_base)
        logger.info("Hybrid index loaded with %d chunk(s)", len(self.knowledge_base))

    def load_index(self) -> None:
        """Load a persisted index or build one from processed documents."""
        from ee_wiki.knowledge.indexer.store import index_exists, load_index

        if index_exists(self.config.indexes_dir):
            persisted = load_index(self.config.indexes_dir)
            self._apply_loaded_index(
                persisted.chunks,
                persisted.embeddings,
                persisted.bm25_corpus,
            )
            return

        logger.info("No persisted index found; building from processed documents")
        from ee_wiki.knowledge.indexer.build import build_index_from_processed
        from ee_wiki.knowledge.indexer.store import load_index

        build_index_from_processed(self.config)
        persisted = load_index(self.config.indexes_dir)
        self._apply_loaded_index(
            persisted.chunks,
            persisted.embeddings,
            persisted.bm25_corpus,
        )

    def build_index(self) -> None:
        """Rebuild and load the hybrid index from processed documents."""
        from ee_wiki.knowledge.indexer.build import build_index_from_processed
        from ee_wiki.knowledge.indexer.store import load_index

        build_index_from_processed(self.config)
        persisted = load_index(self.config.indexes_dir)
        self._apply_loaded_index(
            persisted.chunks,
            persisted.embeddings,
            persisted.bm25_corpus,
        )

    def _apply_document_type_filter(
        self,
        chunks: list[HybridChunk],
        document_type: str | None,
    ) -> list[HybridChunk]:
        if not document_type:
            return chunks
        return [
            chunk
            for chunk in chunks
            if chunk.metadata.get("document_type") == document_type
        ]

    def _filter_by_scope(
        self,
        *,
        target_project: str | None,
        target_build: str | None,
        document_type: str | None = None,
    ) -> tuple[list[HybridChunk], dict[tuple[str, str], int]]:
        if not target_project:
            filtered = self.knowledge_base
            return self._apply_document_type_filter(filtered, document_type), {}

        if self.config.retrieval.scope_inheritance and target_build:
            scopes = expand_retrieval_scope(
                target_project,
                target_build,
                self.config.data_layout,
            )
            scope_set = set(scopes)
            scope_ranks = {pair: rank for rank, pair in enumerate(scopes)}
            filtered = [
                chunk
                for chunk in self.knowledge_base
                if (chunk.metadata.get("project"), chunk.metadata.get("build")) in scope_set
            ]
            return (
                self._apply_document_type_filter(filtered, document_type),
                scope_ranks,
            )

        filtered = [
            chunk
            for chunk in self.knowledge_base
            if chunk.metadata.get("project") == target_project
            and (target_build is None or chunk.metadata.get("build") == target_build)
        ]
        return self._apply_document_type_filter(filtered, document_type), {}

    def retrieve(
        self,
        query: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        document_type: str | None = None,
        top_k_dense: int | None = None,
        top_k_sparse: int | None = None,
        top_k_final: int | None = None,
    ) -> RetrievalResult:
        """Run scope filter → dense + sparse recall → rerank → scope priority.

        Args:
            query: Natural language or keyword search string.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            document_type: Optional document type filter (e.g. ``schematic``).
            top_k_dense: Dense recall count override.
            top_k_sparse: Sparse recall count override.
            top_k_final: Final reranked result count override.

        Returns:
            Ranked chunks with citation metadata and top rerank score.
        """
        if not self.knowledge_base:
            self.load_index()
        if not self.knowledge_base:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        dense_k = top_k_dense or self.config.retrieval.top_k_dense
        sparse_k = top_k_sparse or self.config.retrieval.top_k_sparse
        final_k = top_k_final or self.config.retrieval.top_k_final
        search_query = expand_hw_query(query)
        if search_query != query:
            logger.info("Expanded retrieval query: %s", search_query)

        resolved_document_type = effective_document_type(query, document_type)
        schematic_preferred = prefers_schematic_sources(query)
        if schematic_preferred:
            dense_k = top_k_dense or self.config.retrieval.top_k_embed
            sparse_k = top_k_sparse or self.config.retrieval.top_k_bm25
            final_k = top_k_final or max(self.config.retrieval.top_k_final, 12)

        filtered, scope_ranks = self._filter_by_scope(
            target_project=target_project,
            target_build=target_build,
            document_type=resolved_document_type,
        )
        if not filtered:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        self._load_embed_model()
        with self._model_lock:
            query_emb = self._embed_model.encode(search_query, convert_to_numpy=True)
        dense_scores: list[tuple[float, HybridChunk]] = []
        for chunk in filtered:
            if chunk.embedding is None:
                continue
            score = float(
                np.dot(query_emb, chunk.embedding)
                / (np.linalg.norm(query_emb) * np.linalg.norm(chunk.embedding) + 1e-12)
            )
            dense_scores.append((score, chunk))
        dense_selected = [
            item[1]
            for item in sorted(dense_scores, key=lambda item: item[0], reverse=True)[:dense_k]
        ]

        sparse_selected: list[HybridChunk] = []
        if self.bm25 is not None:
            query_tokens = tokenize_hw_text(search_query)
            all_scores = self.bm25.get_scores(query_tokens)
            sparse_scores: list[tuple[float, HybridChunk]] = []
            for chunk in filtered:
                position = self._chunk_positions.get(chunk.chunk_id)
                if position is None:
                    continue
                sparse_scores.append((float(all_scores[position]), chunk))
            sparse_selected = [
                item[1]
                for item in sorted(sparse_scores, key=lambda item: item[0], reverse=True)[:sparse_k]
            ]

        combined: list[HybridChunk] = []
        seen: set[str] = set()
        for chunk in dense_selected + sparse_selected:
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                combined.append(chunk)
        if not combined:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        self._load_reranker()
        import torch

        pairs = [
            [search_query, query_focused_excerpt(chunk.content, search_query)]
            for chunk in combined
        ]
        with self._model_lock, torch.no_grad():
            inputs = self._rerank_tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            ).to(self._device)
            logits = self._rerank_model(**inputs).logits.view(-1).float().cpu().numpy()

        top_rerank_score = float(np.max(logits)) if len(logits) else None
        min_score = self.config.retrieval.min_rerank_score
        if (
            min_score is not None
            and top_rerank_score is not None
            and top_rerank_score < min_score
        ):
            logger.info(
                "Retrieval skipped: top rerank score %.3f below min_rerank_score %.3f",
                top_rerank_score,
                min_score,
            )
            return RetrievalResult(chunks=[], top_rerank_score=top_rerank_score)

        def scope_rank(chunk: HybridChunk) -> int:
            pair = (chunk.metadata.get("project"), chunk.metadata.get("build"))
            return scope_ranks.get(pair, 0) if scope_ranks else 0

        boost_tokens = query_boost_tokens(query)

        def keyword_boost(chunk: HybridChunk) -> int:
            if not boost_tokens:
                return 0
            upper = chunk.content.upper()
            content_hits = sum(1 for token in boost_tokens if token.upper() in upper)
            meta_hits = metadata_keyword_boost(chunk.metadata, boost_tokens)
            return content_hits + (meta_hits * 2)

        def document_type_rank(chunk: HybridChunk) -> int:
            if resolved_document_type is not None:
                return 0
            if not schematic_preferred:
                return 0
            if chunk.metadata.get("document_type") == SCHEMATIC_DOCUMENT_TYPE:
                return 0
            return 1

        reranked = [
            item[1]
            for item in sorted(
                zip(logits, combined),
                key=lambda item: (
                    scope_rank(item[1]),
                    document_type_rank(item[1]),
                    -keyword_boost(item[1]),
                    -float(item[0]),
                ),
            )
        ]
        hits = reranked[:final_k]
        if self.config.retrieval.expand_sections:
            hits = expand_retrieved_sections(hits, self._section_index)
        return RetrievalResult(chunks=hits, top_rerank_score=top_rerank_score)
