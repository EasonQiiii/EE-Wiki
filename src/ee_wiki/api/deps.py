"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache

from ee_wiki.api.concurrency import RequestQueueGate
from ee_wiki.common.config import AppConfig, load_config
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.service import RagService

logger = get_logger(__name__)


@lru_cache
def get_config() -> AppConfig:
    """Return cached application configuration."""
    return load_config()


@lru_cache
def get_queue_gate() -> RequestQueueGate:
    """Return cached request queue gate configured from ``api.concurrency``."""
    cfg = get_config().api.concurrency
    return RequestQueueGate(
        max_concurrent=cfg.max_concurrent,
        max_queue_depth=cfg.max_queue_depth,
        retry_after_seconds=cfg.retry_after_seconds,
    )


@lru_cache
def get_rag_service() -> RagService:
    """Return cached RAG service instance."""
    return RagService.from_config(get_config())


def warmup_rag_service() -> None:
    """Preload indexes and retrieval models; LLM loads on first chat request."""
    service = get_rag_service()
    logger.info("Warming up retrieval index and retrieval models...")
    service.engine.load_index()
    service.engine._load_embed_model()
    service.engine._load_reranker()
    logger.info(
        "Retrieval warmup complete. LLM (%s, backend=%s) loads on first chat request.",
        get_config().models.resolve_llm_model(get_config().generation.llm_backend),
        get_config().generation.llm_backend,
    )
