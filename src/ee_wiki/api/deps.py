"""FastAPI dependency providers."""

from __future__ import annotations

from functools import lru_cache

from ee_wiki.common.config import AppConfig, load_config
from ee_wiki.generation.service import RagService


@lru_cache
def get_config() -> AppConfig:
    """Return cached application configuration."""
    return load_config()


@lru_cache
def get_rag_service() -> RagService:
    """Return cached RAG service instance."""
    return RagService.from_config(get_config())
