"""Offline hybrid retrieval engine (embedding + BM25 + reranker).

Ported from legacy ``LocalFaHybridRagEngine`` in BYDEE101 ``temp.py``, adapted to
EE-Wiki processed mirror layout and metadata schema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ee_wiki.common.config import AppConfig
from ee_wiki.common.logging import get_logger
from ee_wiki.retrieval.processed_loader import load_processed_records
from ee_wiki.retrieval.tokenizer import tokenize_hw_text

logger = get_logger(__name__)


@dataclass
class HybridChunk:
    """Indexed chunk with optional embedding vector."""

    chunk_id: str
    content: str
    metadata: dict[str, Any]
    embedding: np.ndarray | None = None


@dataclass
class HybridRagEngine:
    """Hybrid retrieval over processed documents."""

    config: AppConfig
    knowledge_base: list[HybridChunk] = field(default_factory=list)
    bm25: Any | None = None
    _embed_model: Any | None = field(default=None, repr=False)
    _rerank_model: Any | None = field(default=None, repr=False)
    _rerank_tokenizer: Any | None = field(default=None, repr=False)
    _device: str | None = field(default=None, repr=False)

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

    def build_index(self) -> None:
        """Load processed docs and build BM25 + embedding indexes."""
        records = load_processed_records(self.config.processed_dir)
        if not records:
            self.knowledge_base = []
            self.bm25 = None
            return

        self._load_embed_model()
        texts = [record.content for record in records]
        embeddings = self._embed_model.encode(texts, convert_to_numpy=True)

        corpus_tokenized = [tokenize_hw_text(text) for text in texts]
        from rank_bm25 import BM25Okapi

        self.bm25 = BM25Okapi(corpus_tokenized)
        self.knowledge_base = [
            HybridChunk(
                chunk_id=record.chunk_id,
                content=record.content,
                metadata={
                    "project": record.metadata.project,
                    "build": record.metadata.build,
                    "document_type": record.metadata.document_type,
                    "source_file": record.metadata.source_file,
                    "target_file": record.metadata.target_file,
                },
                embedding=embeddings[index],
            )
            for index, record in enumerate(records)
        ]
        logger.info("Hybrid index built with %d chunk(s)", len(self.knowledge_base))

    def retrieve(
        self,
        query: str,
        *,
        target_project: str | None = None,
        top_k_dense: int | None = None,
        top_k_sparse: int | None = None,
        top_k_final: int | None = None,
    ) -> list[HybridChunk]:
        """Run metadata filter → dense + sparse recall → rerank."""
        if not self.knowledge_base:
            self.build_index()
        if not self.knowledge_base:
            return []

        dense_k = top_k_dense or self.config.retrieval.top_k_dense
        sparse_k = top_k_sparse or self.config.retrieval.top_k_sparse
        final_k = top_k_final or self.config.retrieval.top_k_final

        filtered = self.knowledge_base
        if target_project:
            filtered = [
                chunk
                for chunk in self.knowledge_base
                if chunk.metadata.get("project") == target_project
            ]
            if not filtered:
                return []

        query_emb = self._embed_model.encode(query, convert_to_numpy=True)
        dense_scores: list[tuple[float, HybridChunk]] = []
        for chunk in filtered:
            if chunk.embedding is None:
                continue
            score = float(
                np.dot(query_emb, chunk.embedding)
                / (np.linalg.norm(query_emb) * np.linalg.norm(chunk.embedding) + 1e-12)
            )
            dense_scores.append((score, chunk))
        dense_selected = [item[1] for item in sorted(dense_scores, reverse=True)[:dense_k]]

        sparse_selected: list[HybridChunk] = []
        if self.bm25 is not None:
            query_tokens = tokenize_hw_text(query)
            all_scores = self.bm25.get_scores(query_tokens)
            sparse_scores: list[tuple[float, HybridChunk]] = []
            for chunk in filtered:
                idx = self.knowledge_base.index(chunk)
                sparse_scores.append((float(all_scores[idx]), chunk))
            sparse_selected = [
                item[1] for item in sorted(sparse_scores, reverse=True)[:sparse_k]
            ]

        combined: list[HybridChunk] = []
        seen: set[str] = set()
        for chunk in dense_selected + sparse_selected:
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                combined.append(chunk)
        if not combined:
            return []

        self._load_reranker()
        import torch

        pairs = [[query, chunk.content[:512]] for chunk in combined]
        with torch.no_grad():
            inputs = self._rerank_tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors="pt",
                max_length=512,
            ).to(self._device)
            logits = self._rerank_model(inputs).logits.view(-1).float().cpu().numpy()
        reranked = [item[1] for item in sorted(zip(logits, combined), reverse=True)]
        return reranked[:final_k]
