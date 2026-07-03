"""Tests for API dependency concurrency resolution."""

from __future__ import annotations

from dataclasses import replace

from ee_wiki.api.deps import resolve_max_concurrent


def test_resolve_max_concurrent_caps_mlx_to_one(app_config) -> None:
    config = replace(
        app_config,
        generation=replace(app_config.generation, llm_backend="mlx"),
        api=replace(
            app_config.api,
            concurrency=replace(app_config.api.concurrency, max_concurrent=2),
        ),
    )
    assert resolve_max_concurrent(config) == 1


def test_resolve_max_concurrent_allows_transformers_parallelism(app_config) -> None:
    config = replace(
        app_config,
        generation=replace(app_config.generation, llm_backend="transformers"),
        api=replace(
            app_config.api,
            concurrency=replace(app_config.api.concurrency, max_concurrent=2),
        ),
    )
    assert resolve_max_concurrent(config) == 2
