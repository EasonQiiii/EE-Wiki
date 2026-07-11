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
from ee_wiki.common.serialization import metadata_to_dict
from ee_wiki.common.types import Chunk
from ee_wiki.ingestion.path_metadata import expand_retrieval_scope
from ee_wiki.knowledge.indexer.component_index import (
    ComponentHit,
    ComponentIndex,
    load_component_index,
)
from ee_wiki.retrieval.component_lookup import COMPONENT_LOOKUP_BOOST, lookup_tokens
from ee_wiki.retrieval.metadata_boost import metadata_keyword_boost
from ee_wiki.retrieval.query_boost import query_boost_tokens
from ee_wiki.retrieval.query_expand import expand_hw_query
from ee_wiki.retrieval.query_intent import effective_document_type, is_board_interface_pin_query
from ee_wiki.retrieval.rerank_excerpt import query_focused_excerpt
from ee_wiki.retrieval.scope_cascade import (
    ScopeQuotas,
    assemble_mixed_quota,
    build_cascade_phases_from_ranks,
    merge_tier_results,
    should_run_scope_cascade,
)
from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_resolve import _inherit_product_scope_ranks
from ee_wiki.retrieval.section_expand import build_section_index, expand_retrieved_sections
from ee_wiki.retrieval.tokenizer import tokenize_hw_text

logger = get_logger(__name__)


def _is_build_schematic_chunk(
    chunk: HybridChunk,
    *,
    target_project: str | None,
    target_build: str | None,
    enterprise_project: str,
    project_shared_build: str,
) -> bool:
    """Return whether ``chunk`` is a build-specific schematic in scope."""
    if chunk.metadata.get("document_type") != "schematic":
        return False
    project = chunk.metadata.get("project")
    build = chunk.metadata.get("build")
    if not project or not build:
        return False
    if project == enterprise_project or build == project_shared_build:
        return False
    if target_project and project != target_project:
        return False
    if target_build and build != target_build:
        return False
    return True


def _document_type_rank(
    chunk: HybridChunk,
    *,
    board_pin_query: bool,
    enterprise_project: str,
    project_shared_build: str,
) -> int:
    """Lower is better: prefer build schematics over global datasheets for pin queries."""
    if not board_pin_query:
        return 1
    doc_type = chunk.metadata.get("document_type")
    project = chunk.metadata.get("project")
    build = chunk.metadata.get("build")
    if (
        doc_type == "schematic"
        and project != enterprise_project
        and build != project_shared_build
    ):
        return 0
    if doc_type == "datasheet" and project == enterprise_project:
        return 2
    return 1


@dataclass
class HybridChunk:
    """Indexed chunk with optional embedding vector."""

    chunk_id: str
    content: str
    metadata: dict[str, Any]
    citation: dict[str, Any]
    embedding: np.ndarray | None = None
    heading_path: str = ""


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
        heading_path=chunk.heading_path,
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
    _scope_catalog: ScopeCatalog | None = field(default=None, repr=False)
    _component_index: ComponentIndex | None = field(default=None, repr=False)

    def get_scope_catalog(self) -> ScopeCatalog:
        """Return cached product/revision catalog derived from the loaded index."""
        if self._scope_catalog is not None:
            return self._scope_catalog
        if not self.knowledge_base:
            self.load_index()
        self._scope_catalog = ScopeCatalog.from_chunk_metadata(
            self.knowledge_base,
            self.config.data_layout,
        )
        return self._scope_catalog

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
        self._scope_catalog = None
        self._component_index = load_component_index(self.config.indexes_dir)
        self._build_embedding_matrix(embeddings, chunks)
        logger.info("Hybrid index loaded with %d chunk(s)", len(self.knowledge_base))

    def _build_embedding_matrix(
        self, embeddings: np.ndarray, chunks: list[Chunk]
    ) -> None:
        """Precompute an L2-normalized embedding matrix for fast dense scoring.

        Only chunks whose persisted embedding is a usable vector participate.
        Rows align with ``self._embedding_chunk_ids`` so the dense path can map
        a filtered chunk back to its matrix row in O(1) via ``self._embed_id_to_row``.
        """
        rows: list[np.ndarray] = []
        ids: list[str] = []
        for index, chunk in enumerate(chunks):
            emb = embeddings[index] if embeddings is not None else None
            if emb is None:
                continue
            arr = np.asarray(emb, dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if norm < 1e-12:
                continue
            rows.append(arr / norm)
            ids.append(chunk.chunk_id)
        if rows:
            self._embedding_matrix = np.vstack(rows).astype(np.float32, copy=False)
        else:
            self._embedding_matrix = np.zeros((0, 0), dtype=np.float32)
        self._embedding_chunk_ids = ids
        self._embed_id_to_row = {cid: row for row, cid in enumerate(ids)}

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

    def _recall_build_schematic_chunks(
        self,
        filtered: list[HybridChunk],
        search_query: str,
        *,
        target_project: str | None,
        target_build: str | None,
        limit: int,
        bm25_scores: Any | None = None,
    ) -> list[HybridChunk]:
        """Add build-schematic candidates for board interface pin queries.

        ``bm25_scores`` is the precomputed full-corpus BM25 vector from
        ``retrieve()``; passing it avoids recomputing ``get_scores`` for the
        same query. Equivalent results, less redundant work.
        """
        if not is_board_interface_pin_query(search_query) or not target_project:
            return []
        layout = self.config.data_layout
        candidates = [
            chunk
            for chunk in filtered
            if _is_build_schematic_chunk(
                chunk,
                target_project=target_project,
                target_build=target_build,
                enterprise_project=layout.enterprise_project,
                project_shared_build=layout.project_shared_build,
            )
        ]
        if not candidates or bm25_scores is None:
            return []

        scored: list[tuple[float, HybridChunk]] = []
        for chunk in candidates:
            position = self._chunk_positions.get(chunk.chunk_id)
            if position is None:
                continue
            scored.append((float(bm25_scores[position]), chunk))
        return [
            item[1]
            for item in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]
        ]

    def _filter_by_scope(
        self,
        *,
        target_project: str | None,
        target_build: str | None,
        document_type: str | None = None,
        scope_ranks_override: dict[tuple[str, str], int] | None = None,
    ) -> tuple[list[HybridChunk], dict[tuple[str, str], int]]:
        if scope_ranks_override:
            scope_set = set(scope_ranks_override)
            filtered = [
                chunk
                for chunk in self.knowledge_base
                if (chunk.metadata.get("project"), chunk.metadata.get("build")) in scope_set
            ]
            return (
                self._apply_document_type_filter(filtered, document_type),
                scope_ranks_override,
            )

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

    def _resolve_scope_ranks(
        self,
        *,
        target_project: str | None,
        target_build: str | None,
        scope_ranks_override: dict[tuple[str, str], int] | None,
    ) -> dict[tuple[str, str], int]:
        """Build scope rank map for cascade or flat inherited retrieval."""
        if scope_ranks_override:
            return scope_ranks_override
        layout = self.config.data_layout
        if not target_project:
            return {}
        if self.config.retrieval.scope_inheritance:
            if target_build:
                scopes = expand_retrieval_scope(
                    target_project,
                    target_build,
                    layout,
                )
                return {pair: rank for rank, pair in enumerate(scopes)}
            catalog = self.get_scope_catalog()
            return _inherit_product_scope_ranks(target_project, catalog, layout)
        if target_build:
            return {(target_project, target_build): 0}
        return {}

    def _filter_chunks_by_scope_pairs(
        self,
        scope_pairs: set[tuple[str, str]],
        document_type: str | None,
    ) -> list[HybridChunk]:
        """Return indexed chunks whose metadata pair is in ``scope_pairs``."""
        filtered = [
            chunk
            for chunk in self.knowledge_base
            if (chunk.metadata.get("project"), chunk.metadata.get("build")) in scope_pairs
        ]
        return self._apply_document_type_filter(filtered, document_type)

    def _encode_query(self, search_query: str) -> np.ndarray:
        """Embed the search query once per retrieval request."""
        self._load_embed_model()
        with self._model_lock:
            return self._embed_model.encode(search_query, convert_to_numpy=True)

    def _bm25_scores_for_query(self, search_query: str) -> Any | None:
        """Return full-corpus BM25 scores for ``search_query``, or ``None``."""
        if self.bm25 is None:
            return None
        query_tokens = tokenize_hw_text(search_query)
        return self.bm25.get_scores(query_tokens)

    def _dense_recall(
        self,
        filtered: list[HybridChunk],
        query_emb: np.ndarray,
        *,
        dense_k: int,
    ) -> list[HybridChunk]:
        """Return top dense embedding matches from ``filtered``."""
        matrix = getattr(self, "_embedding_matrix", None)
        id_to_row = getattr(self, "_embed_id_to_row", None)
        if matrix is not None and matrix.shape[0] > 0 and id_to_row:
            q = np.asarray(query_emb, dtype=np.float32)
            q = q / (np.linalg.norm(q) + 1e-12)
            row_idx: list[int] = []
            row_ids: list[int] = []
            for i, chunk in enumerate(filtered):
                r = id_to_row.get(chunk.chunk_id)
                if r is not None:
                    row_idx.append(i)
                    row_ids.append(r)
            if row_ids:
                sims = matrix[row_ids] @ q
                k = min(dense_k, sims.shape[0])
                order = np.argsort(-sims)[:k]
                return [filtered[row_idx[j]] for j in order]
            return []

        dense_scores: list[tuple[float, HybridChunk]] = []
        for chunk in filtered:
            if chunk.embedding is None:
                continue
            score = float(
                np.dot(query_emb, chunk.embedding)
                / (np.linalg.norm(query_emb) * np.linalg.norm(chunk.embedding) + 1e-12)
            )
            dense_scores.append((score, chunk))
        return [
            item[1]
            for item in sorted(dense_scores, key=lambda item: item[0], reverse=True)[:dense_k]
        ]

    def _sparse_recall(
        self,
        filtered: list[HybridChunk],
        all_scores: Any | None,
        *,
        sparse_k: int,
    ) -> list[HybridChunk]:
        """Return top BM25 matches from ``filtered``."""
        if all_scores is None:
            return []
        sparse_scores: list[tuple[float, HybridChunk]] = []
        for chunk in filtered:
            position = self._chunk_positions.get(chunk.chunk_id)
            if position is None:
                continue
            sparse_scores.append((float(all_scores[position]), chunk))
        return [
            item[1]
            for item in sorted(sparse_scores, key=lambda item: item[0], reverse=True)[:sparse_k]
        ]

    def _recall_candidates(
        self,
        filtered: list[HybridChunk],
        *,
        query: str,
        search_query: str,
        query_emb: np.ndarray,
        all_scores: Any | None,
        dense_k: int,
        sparse_k: int,
        target_project: str | None,
        target_build: str | None,
    ) -> list[HybridChunk]:
        """Merge dense, sparse, and optional schematic-boost recall."""
        dense_selected = self._dense_recall(filtered, query_emb, dense_k=dense_k)
        sparse_selected = self._sparse_recall(filtered, all_scores, sparse_k=sparse_k)

        combined: list[HybridChunk] = []
        seen: set[str] = set()
        for chunk in dense_selected + sparse_selected:
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                combined.append(chunk)

        board_pin_query = is_board_interface_pin_query(search_query)
        if board_pin_query and target_project:
            schematic_selected = self._recall_build_schematic_chunks(
                filtered,
                search_query,
                target_project=target_project,
                target_build=target_build,
                limit=dense_k,
                bm25_scores=all_scores,
            )
            for chunk in schematic_selected:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    combined.append(chunk)
            if schematic_selected:
                logger.info(
                    "Added %d build-schematic chunk(s) for board interface pin query",
                    len(schematic_selected),
                )
        return combined

    def _rerank_logits(
        self,
        combined: list[HybridChunk],
        search_query: str,
    ) -> np.ndarray:
        """Score candidate chunks with the cross-encoder reranker."""
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
            return (
                self._rerank_model(**inputs)
                .logits.view(-1)
                .float()
                .cpu()
                .numpy()
            )

    def _sort_reranked_candidates(
        self,
        logits: np.ndarray,
        combined: list[HybridChunk],
        *,
        query: str,
        search_query: str,
        scope_ranks: dict[tuple[str, str], int],
        target_project: str | None = None,
        target_build: str | None = None,
    ) -> list[tuple[float, HybridChunk]]:
        """Sort reranked candidates; lower scope rank and higher logit win."""

        def scope_rank(chunk: HybridChunk) -> int:
            pair = (chunk.metadata.get("project"), chunk.metadata.get("build"))
            return scope_ranks.get(pair, 0) if scope_ranks else 0

        boost_tokens = query_boost_tokens(query)
        layout = self.config.data_layout
        board_pin_query = is_board_interface_pin_query(search_query)
        component_chunk_ids = lookup_tokens(
            self._component_index,
            boost_tokens,
            layout=layout,
            target_project=target_project,
            target_build=target_build,
            scope_inheritance=self.config.retrieval.scope_inheritance,
        )

        def keyword_boost(chunk: HybridChunk) -> int:
            if not boost_tokens:
                return 0
            upper = chunk.content.upper()
            content_hits = sum(1 for token in boost_tokens if token.upper() in upper)
            meta_hits = metadata_keyword_boost(chunk.metadata, boost_tokens)
            component_hits = (
                COMPONENT_LOOKUP_BOOST if chunk.chunk_id in component_chunk_ids else 0
            )
            return content_hits + (meta_hits * 2) + component_hits

        return sorted(
            zip(logits, combined),
            key=lambda item: (
                scope_rank(item[1]),
                _document_type_rank(
                    item[1],
                    board_pin_query=board_pin_query,
                    enterprise_project=layout.enterprise_project,
                    project_shared_build=layout.project_shared_build,
                ),
                -keyword_boost(item[1]),
                -float(item[0]),
            ),
        )

    def _retrieve_from_filtered(
        self,
        filtered: list[HybridChunk],
        *,
        query: str,
        search_query: str,
        query_emb: np.ndarray,
        all_scores: Any | None,
        dense_k: int,
        sparse_k: int,
        target_project: str | None,
        target_build: str | None,
        scope_ranks: dict[tuple[str, str], int],
    ) -> tuple[list[tuple[float, HybridChunk]], float | None]:
        """Recall, rerank, and sort candidates from a pre-filtered chunk pool."""
        combined = self._recall_candidates(
            filtered,
            query=query,
            search_query=search_query,
            query_emb=query_emb,
            all_scores=all_scores,
            dense_k=dense_k,
            sparse_k=sparse_k,
            target_project=target_project,
            target_build=target_build,
        )
        if not combined:
            return [], None

        logits = self._rerank_logits(combined, search_query)
        paired_logits = logits[: len(combined)]
        top_rerank_score = float(np.max(paired_logits)) if len(paired_logits) else None
        scored = self._sort_reranked_candidates(
            paired_logits,
            combined,
            query=query,
            search_query=search_query,
            scope_ranks=scope_ranks,
            target_project=target_project,
            target_build=target_build,
        )
        return [(float(score), chunk) for score, chunk in scored], top_rerank_score

    def _scope_quotas(self) -> ScopeQuotas:
        retrieval = self.config.retrieval
        return ScopeQuotas(
            build=retrieval.scope_quota_build,
            common=retrieval.scope_quota_common,
            global_=retrieval.scope_quota_global,
        )

    def _retrieve_cascade(
        self,
        *,
        query: str,
        search_query: str,
        target_project: str | None,
        target_build: str | None,
        document_type: str | None,
        scope_ranks: dict[tuple[str, str], int],
        dense_k: int,
        sparse_k: int,
        final_k: int,
    ) -> RetrievalResult:
        """Run tier cascade: build → project_common → global with mixed quotas."""
        from ee_wiki.retrieval.scope_cascade import SCOPE_TIER_GLOBAL

        layout = self.config.data_layout
        phases = build_cascade_phases_from_ranks(scope_ranks, layout)
        threshold = self.config.retrieval.scope_sufficient_rerank
        quotas = self._scope_quotas()

        query_emb = self._encode_query(search_query)
        all_scores = self._bm25_scores_for_query(search_query)

        reranked_by_tier: dict[int, list[tuple[float, HybridChunk]]] = {}
        primary_tier = SCOPE_TIER_GLOBAL
        primary_sufficient = False
        top_rerank_score: float | None = None

        for phase in phases:
            filtered = self._filter_chunks_by_scope_pairs(
                set(phase.scope_pairs),
                document_type,
            )
            if not filtered:
                continue

            scored, phase_top = self._retrieve_from_filtered(
                filtered,
                query=query,
                search_query=search_query,
                query_emb=query_emb,
                all_scores=all_scores,
                dense_k=dense_k,
                sparse_k=sparse_k,
                target_project=target_project,
                target_build=target_build,
                scope_ranks=scope_ranks,
            )
            reranked_by_tier = merge_tier_results(reranked_by_tier, phase.tier, scored)
            if phase_top is not None:
                top_rerank_score = (
                    phase_top if top_rerank_score is None else max(top_rerank_score, phase_top)
                )
            if scored:
                primary_tier = phase.tier

            logger.info(
                "scope_cascade phase tier=%d pairs=%d hits=%d top_rerank=%s",
                phase.tier,
                len(phase.scope_pairs),
                len(scored),
                f"{phase_top:.3f}" if phase_top is not None else "none",
            )

            if scored and phase_top is not None and phase_top >= threshold:
                primary_tier = phase.tier
                primary_sufficient = True
                logger.info(
                    "scope_cascade primary_tier=%d sufficient at rerank %.3f",
                    primary_tier,
                    phase_top,
                )
                break

        if primary_sufficient:
            for phase in phases:
                if phase.tier <= primary_tier or phase.tier in reranked_by_tier:
                    continue
                filtered = self._filter_chunks_by_scope_pairs(
                    set(phase.scope_pairs),
                    document_type,
                )
                if not filtered:
                    continue
                scored, phase_top = self._retrieve_from_filtered(
                    filtered,
                    query=query,
                    search_query=search_query,
                    query_emb=query_emb,
                    all_scores=all_scores,
                    dense_k=dense_k,
                    sparse_k=sparse_k,
                    target_project=target_project,
                    target_build=target_build,
                    scope_ranks=scope_ranks,
                )
                reranked_by_tier = merge_tier_results(reranked_by_tier, phase.tier, scored)
                if phase_top is not None:
                    top_rerank_score = (
                        phase_top if top_rerank_score is None else max(top_rerank_score, phase_top)
                    )

        if not reranked_by_tier:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        hits = assemble_mixed_quota(
            reranked_by_tier,
            primary_tier=primary_tier,
            final_k=final_k,
            quotas=quotas,
        )
        if hits:
            selected_scores = []
            for tier_chunks in reranked_by_tier.values():
                hit_ids = {chunk.chunk_id for chunk in hits}
                for score, chunk in tier_chunks:
                    if chunk.chunk_id in hit_ids:
                        selected_scores.append(score)
            if selected_scores:
                top_rerank_score = max(selected_scores)

        return RetrievalResult(chunks=hits, top_rerank_score=top_rerank_score)

    def _retrieve_flat(
        self,
        *,
        query: str,
        search_query: str,
        target_project: str | None,
        target_build: str | None,
        document_type: str | None,
        scope_ranks: dict[tuple[str, str], int],
        scope_ranks_override: dict[tuple[str, str], int] | None,
        dense_k: int,
        sparse_k: int,
        final_k: int,
    ) -> RetrievalResult:
        """Parallel-pool retrieval (legacy path when cascade is disabled)."""
        filtered, resolved_ranks = self._filter_by_scope(
            target_project=target_project,
            target_build=target_build,
            document_type=document_type,
            scope_ranks_override=scope_ranks_override,
        )
        if not filtered:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        query_emb = self._encode_query(search_query)
        all_scores = self._bm25_scores_for_query(search_query)
        scored, top_rerank_score = self._retrieve_from_filtered(
            filtered,
            query=query,
            search_query=search_query,
            query_emb=query_emb,
            all_scores=all_scores,
            dense_k=dense_k,
            sparse_k=sparse_k,
            target_project=target_project,
            target_build=target_build,
            scope_ranks=resolved_ranks or scope_ranks,
        )
        if not scored:
            return RetrievalResult(chunks=[], top_rerank_score=None)

        hits = [chunk for _, chunk in scored[:final_k]]
        return RetrievalResult(chunks=hits, top_rerank_score=top_rerank_score)

    def search_components(
        self,
        query: str,
        *,
        target_project: str | None = None,
        target_build: str | None = None,
        limit: int = 20,
    ) -> list[ComponentHit]:
        """Look up part numbers or designators in the component index.

        Args:
            query: Part number or schematic reference designator.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            limit: Maximum number of hits to return.

        Returns:
            Matching component hits scoped to the requested project/build.
        """
        from ee_wiki.retrieval.component_lookup import search_components as lookup_components

        if not self.knowledge_base:
            self.load_index()
        if self._component_index is None:
            self._component_index = load_component_index(self.config.indexes_dir)
        return lookup_components(
            self._component_index,
            query,
            layout=self.config.data_layout,
            target_project=target_project,
            target_build=target_build,
            scope_inheritance=self.config.retrieval.scope_inheritance,
            limit=limit,
        )

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
        scope_ranks_override: dict[tuple[str, str], int] | None = None,
    ) -> RetrievalResult:
        """Run scope filter → dense + sparse recall → rerank → scope priority.

        When ``scope_cascade`` is enabled with scope inheritance, retrieval runs
        tier phases (build → project_common → global) instead of a single mixed pool.

        Args:
            query: Natural language or keyword search string.
            target_project: Optional project metadata filter.
            target_build: Optional build metadata filter.
            document_type: Optional document type filter (e.g. ``schematic``).
            top_k_dense: Dense recall count override.
            top_k_sparse: Sparse recall count override.
            top_k_final: Final reranked result count override.
            scope_ranks_override: Optional precomputed scope rank map for multi-pair filters.

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
        scope_ranks = self._resolve_scope_ranks(
            target_project=target_project,
            target_build=target_build,
            scope_ranks_override=scope_ranks_override,
        )

        if should_run_scope_cascade(
            scope_inheritance=self.config.retrieval.scope_inheritance,
            scope_cascade=self.config.retrieval.scope_cascade,
            target_project=target_project,
            scope_ranks=scope_ranks,
        ):
            result = self._retrieve_cascade(
                query=query,
                search_query=search_query,
                target_project=target_project,
                target_build=target_build,
                document_type=resolved_document_type,
                scope_ranks=scope_ranks,
                dense_k=dense_k,
                sparse_k=sparse_k,
                final_k=final_k,
            )
        else:
            result = self._retrieve_flat(
                query=query,
                search_query=search_query,
                target_project=target_project,
                target_build=target_build,
                document_type=resolved_document_type,
                scope_ranks=scope_ranks,
                scope_ranks_override=scope_ranks_override,
                dense_k=dense_k,
                sparse_k=sparse_k,
                final_k=final_k,
            )

        min_score = self.config.retrieval.min_rerank_score
        if (
            min_score is not None
            and result.top_rerank_score is not None
            and result.top_rerank_score < min_score
        ):
            logger.info(
                "Retrieval skipped: top rerank score %.3f below min_rerank_score %.3f",
                result.top_rerank_score,
                min_score,
            )
            return RetrievalResult(chunks=[], top_rerank_score=result.top_rerank_score)

        hits = result.chunks
        if self.config.retrieval.expand_sections:
            hits = expand_retrieved_sections(hits, self._section_index)
        return RetrievalResult(chunks=hits, top_rerank_score=result.top_rerank_score)
