"""Route user queries to assistant-meta or engineering RAG paths."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from ee_wiki.common.config import AppConfig
from ee_wiki.common.errors import ConfigError
from ee_wiki.common.logging import get_logger
from ee_wiki.retrieval.hybrid.engine import HybridRagEngine

logger = get_logger(__name__)


class QueryRoute(StrEnum):
    """High-level query routing destination."""

    ASSISTANT_META = "assistant_meta"
    ENGINEERING = "engineering"


@dataclass(frozen=True)
class IntentExemplars:
    """Exemplar phrases grouped by routing destination."""

    assistant_meta: tuple[str, ...]
    engineering: tuple[str, ...]


def resolve_intent_exemplars_path(repo_root: Path) -> Path:
    """Return the path to ``config/intent_exemplars.yaml``."""
    return (repo_root / "config" / "intent_exemplars.yaml").resolve()


@lru_cache
def load_intent_exemplars(repo_root: str) -> IntentExemplars:
    """Load and cache intent exemplars from configuration.

    Args:
        repo_root: Repository root as a string for cache key stability.

    Returns:
        Parsed exemplar groups.

    Raises:
        ConfigError: If the YAML file is missing or invalid.
    """
    path = resolve_intent_exemplars_path(Path(repo_root))
    if not path.is_file():
        raise ConfigError(f"Intent exemplars file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ConfigError(f"Intent exemplars must be a mapping: {path}")

    assistant = raw.get("assistant_meta", [])
    engineering = raw.get("engineering", [])
    if not isinstance(assistant, list) or not isinstance(engineering, list):
        raise ConfigError(f"assistant_meta and engineering must be lists in {path}")
    if not assistant or not engineering:
        raise ConfigError(f"assistant_meta and engineering must be non-empty in {path}")

    return IntentExemplars(
        assistant_meta=tuple(str(item) for item in assistant),
        engineering=tuple(str(item) for item in engineering),
    )


def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    return float(
        np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right) + 1e-12)
    )


def _best_exemplar_score(query_embedding: np.ndarray, exemplar_embeddings: np.ndarray) -> float:
    if len(exemplar_embeddings) == 0:
        return -1.0
    scores = [
        _cosine_similarity(query_embedding, exemplar_embeddings[index])
        for index in range(len(exemplar_embeddings))
    ]
    return max(scores)


def classify_query_route(
    question: str,
    engine: HybridRagEngine,
    config: AppConfig,
) -> QueryRoute:
    """Classify whether a question is about the assistant or engineering knowledge.

    Uses embedding similarity against a small exemplar set in
    ``config/intent_exemplars.yaml``. When scores are ambiguous, defaults to
    ``engineering`` so factual questions are not accidentally answered without
    retrieval.

    Args:
        question: Raw user question.
        engine: Hybrid engine providing the embedding model.
        config: Application configuration.

    Returns:
        Routing destination for the query.
    """
    if not config.generation.intent_routing:
        return QueryRoute.ENGINEERING

    normalized = question.strip()
    if not normalized:
        return QueryRoute.ENGINEERING

    exemplars = load_intent_exemplars(str(config.repo_root))
    texts = [normalized, *exemplars.assistant_meta, *exemplars.engineering]
    engine._load_embed_model()
    embeddings = engine._embed_model.encode(texts, convert_to_numpy=True)
    query_embedding = embeddings[0]
    assistant_count = len(exemplars.assistant_meta)
    assistant_embeddings = embeddings[1 : 1 + assistant_count]
    engineering_embeddings = embeddings[1 + assistant_count :]

    assistant_score = _best_exemplar_score(query_embedding, assistant_embeddings)
    engineering_score = _best_exemplar_score(query_embedding, engineering_embeddings)
    margin = config.generation.intent_similarity_margin

    if assistant_score >= engineering_score + margin:
        logger.info(
            "Intent route=assistant_meta (assistant=%.3f engineering=%.3f margin=%.3f)",
            assistant_score,
            engineering_score,
            margin,
        )
        return QueryRoute.ASSISTANT_META

    logger.info(
        "Intent route=engineering (assistant=%.3f engineering=%.3f margin=%.3f)",
        assistant_score,
        engineering_score,
        margin,
    )
    return QueryRoute.ENGINEERING
