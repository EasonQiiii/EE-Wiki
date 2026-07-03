"""Tests for embedding-based query intent routing."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ee_wiki.generation.intent_router import (
    QueryRoute,
    classify_query_route,
    load_intent_exemplars,
)


@pytest.fixture
def intent_engine(app_config):
    exemplars = load_intent_exemplars(str(app_config.repo_root))
    assistant_vectors = np.array(
        [[1.0, 0.0, 0.0], [0.95, 0.05, 0.0], [0.9, 0.1, 0.0]],
        dtype=np.float32,
    )
    engineering_vectors = np.array(
        [[0.0, 1.0, 0.0], [0.05, 0.95, 0.0], [0.0, 0.9, 0.1]],
        dtype=np.float32,
    )
    assistant_embeddings = np.vstack(
        [assistant_vectors[index % len(assistant_vectors)] for index in range(len(exemplars.assistant_meta))]
    )
    engineering_embeddings = np.vstack(
        [engineering_vectors[index % len(engineering_vectors)] for index in range(len(exemplars.engineering))]
    )

    def _encode(texts, convert_to_numpy=True):
        del convert_to_numpy
        query = texts[0]
        if "RMII" in query or "VBAT" in query:
            query_embedding = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        else:
            query_embedding = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        return np.vstack([query_embedding, assistant_embeddings, engineering_embeddings])

    engine = MagicMock()
    engine._embed_model = MagicMock()
    engine._embed_model.encode.side_effect = _encode
    engine._load_embed_model = MagicMock()
    return engine


def test_load_intent_exemplars(app_config) -> None:
    exemplars = load_intent_exemplars(str(app_config.repo_root))
    assert exemplars.assistant_meta
    assert exemplars.engineering


@pytest.mark.parametrize(
    "question",
    [
        "你可以做什么",
        "你的角色是什么",
        "可以给你改名叫小e吗",
    ],
)
def test_classify_routes_assistant_meta(intent_engine, app_config, question: str) -> None:
    route = classify_query_route(question, intent_engine, app_config)
    assert route is QueryRoute.ASSISTANT_META


@pytest.mark.parametrize(
    "question",
    [
        "RMII 连接了哪些器件",
        "VBAT 电压是多少",
    ],
)
def test_classify_routes_engineering(intent_engine, app_config, question: str) -> None:
    route = classify_query_route(question, intent_engine, app_config)
    assert route is QueryRoute.ENGINEERING


def test_classify_disabled_returns_engineering(intent_engine, app_config) -> None:
    config = replace(
        app_config,
        generation=replace(app_config.generation, intent_routing=False),
    )
    route = classify_query_route("你是谁", intent_engine, config)
    assert route is QueryRoute.ENGINEERING
