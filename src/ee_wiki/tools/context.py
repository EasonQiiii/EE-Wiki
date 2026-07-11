"""Shared runtime context for EE-Wiki tools."""

from __future__ import annotations

from dataclasses import dataclass

from ee_wiki.common.config import AppConfig, load_config
from ee_wiki.common.logging import get_logger
from ee_wiki.retrieval.hybrid.engine import HybridRagEngine

logger = get_logger(__name__)


@dataclass
class ToolContext:
    """Read-only retrieval context for tool handlers."""

    config: AppConfig
    engine: HybridRagEngine

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ToolContext:
        """Build a tool context and preload the retrieval index.

        Args:
            config: Optional application configuration. Defaults to :func:`load_config`.

        Returns:
            Initialized tool context with a loaded hybrid retrieval engine.
        """
        resolved = config or load_config()
        engine = HybridRagEngine(resolved)
        logger.info("Loading retrieval index for tools...")
        engine.load_index()
        engine._load_embed_model()
        engine._load_reranker()
        logger.info("Tool context ready (%d chunk(s))", len(engine.knowledge_base))
        return cls(config=resolved, engine=engine)
