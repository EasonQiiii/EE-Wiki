"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache

from ee_wiki.api.concurrency import RequestQueueGate
from ee_wiki.common.config import AppConfig, load_config
from ee_wiki.common.logging import get_logger
from ee_wiki.connectivity.authority import AuthorityPolicy
from ee_wiki.connectivity.query import ConnectivityQuery, open_connectivity_query
from ee_wiki.generation.service import RagService
from ee_wiki.graph.power_tree import PowerTreeQuery, open_power_query
from ee_wiki.graph.query import GraphQuery, open_query
from ee_wiki.graph.store import GraphStoreError, JsonlGraphStore, graph_exists
from ee_wiki.knowledge.indexer.case_index import CaseIndexError, load_case_index
from ee_wiki.rules.engine import RuleEngine, open_rule_engine
from ee_wiki.rules.errors import RulePackError

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


@lru_cache
def get_graph_query() -> GraphQuery | None:
    """Return a cached graph query handle, or ``None`` if the bundle is missing.

    Returns:
        :class:`GraphQuery` when ``data/graph/`` exists and loads, else
        ``None`` (routes should map to HTTP 503).
    """
    config = get_config()
    if not graph_exists(config.graph_dir):
        logger.warning("Graph bundle missing under %s", config.graph_dir)
        return None
    try:
        graph = JsonlGraphStore().load_graph(config.graph_dir)
    except GraphStoreError as exc:
        logger.warning("Failed to load knowledge graph: %s", exc)
        return None
    return open_query(
        graph,
        layout=config.data_layout,
        scope_inheritance=config.graph.scope_inheritance,
    )


@lru_cache
def get_power_tree_query() -> PowerTreeQuery | None:
    """Return a cached power-tree query handle, or ``None`` if graph is missing.

    Returns:
        :class:`PowerTreeQuery` when ``data/graph/`` exists and loads, else
        ``None`` (routes should map to HTTP 503).
    """
    config = get_config()
    if not config.graph.power_tree:
        logger.info("graph.power_tree disabled; power queries unavailable")
        return None
    gq = get_graph_query()
    if gq is None:
        return None
    return open_power_query(gq)


@lru_cache
def get_rule_engine() -> RuleEngine | None:
    """Return a cached rules engine, or ``None`` when unavailable.

    Returns:
        :class:`RuleEngine` when rules are enabled, the pack loads, and the
        graph bundle exists; else ``None`` (routes should map to HTTP 503).
    """
    config = get_config()
    if not config.rules.enabled:
        logger.info("rules.enabled is false; rules engine unavailable")
        return None
    gq = get_graph_query()
    if gq is None:
        return None
    power = open_power_query(gq) if config.graph.power_tree else None
    cases = None
    try:
        cases = load_case_index(config.indexes_dir)
    except CaseIndexError as exc:
        logger.warning("Failed to load case index for rules: %s", exc)
    try:
        return open_rule_engine(
            gq,
            config.rules_pack_dir,
            power_query=power,
            case_index=cases,
        )
    except RulePackError as exc:
        logger.warning("Failed to load rule pack: %s", exc)
        return None


@lru_cache
def get_connectivity_query() -> ConnectivityQuery | None:
    """Return a cached connectivity query handle, or ``None`` if unavailable.

    Returns:
        :class:`ConnectivityQuery` when connectivity is enabled and at least
        one ``*.connectivity.json`` sidecar loads; else ``None`` (routes map
        to HTTP 503).
    """
    config = get_config()
    if not config.schematic_pdf.connectivity.enabled:
        logger.info("schematic_pdf.connectivity.enabled is false; connectivity queries unavailable")
        return None
    query = open_connectivity_query(
        processed_dir=config.processed_dir,
        layout=config.data_layout,
        scope_inheritance=config.retrieval.scope_inheritance,
        authority=AuthorityPolicy.from_config(config.schematic_pdf.connectivity),
    )
    if not query.documents:
        logger.warning(
            "No connectivity sidecars under %s; re-ingest sch/ PDFs",
            config.processed_dir,
        )
        return None
    return query


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
