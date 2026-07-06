"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache

from ee_wiki.api.concurrency import RequestQueueGate
from ee_wiki.common.config import AppConfig, load_config
from ee_wiki.common.logging import get_logger
from ee_wiki.generation.service import RagService

logger = get_logger(__name__)


def resolve_max_concurrent(config: AppConfig) -> int:
    """Return the effective RAG concurrency limit for the configured LLM backend.

    MLX shares one GPU stream and one dedicated inference worker thread per
    process, so more than one in-flight generation deadlocks or corrupts state.
    """
    configured = config.api.concurrency.max_concurrent
    if config.generation.llm_backend == "mlx" and configured > 1:
        logger.warning(
            "api.concurrency.max_concurrent=%s is not supported with "
            "generation.llm_backend=mlx; using 1 (one MLX generation slot).",
            configured,
        )
        return 1
    return configured


@lru_cache
def get_config() -> AppConfig:
    """Return cached application configuration."""
    return load_config()


@lru_cache
def get_queue_gate() -> RequestQueueGate:
    """Return cached request queue gate configured from ``api.concurrency``."""
    config = get_config()
    cfg = config.api.concurrency
    max_concurrent = resolve_max_concurrent(config)
    return RequestQueueGate(
        max_concurrent=max_concurrent,
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
    config = get_config()
    logger.info("Warming up retrieval index and retrieval models...")
    service.engine.load_index()
    service.engine._load_embed_model()
    service.engine._load_reranker()
    backend = config.generation.llm_backend
    if backend == "openai":
        logger.info(
            "Retrieval warmup complete. LLM delegated to %s (model=%s).",
            config.generation.openai_base_url,
            config.generation.openai_model,
        )
        return
    logger.info(
        "Retrieval warmup complete. LLM (%s, backend=%s) loads on first chat request.",
        config.models.resolve_llm_model(backend),
        backend,
    )
