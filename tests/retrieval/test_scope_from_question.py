"""Tests for chat question → product/project/build scope recovery."""

from __future__ import annotations

from pathlib import Path

from ee_wiki.common.config import load_config
from ee_wiki.retrieval.scope_from_question import (
    infer_scope_from_aliases,
    merge_scope_from_question,
)


def test_logan_p1_trace_question_maps_ipad_logan_p1(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    q = "logan p1 原理图DP_TBTSNK1_ML_C_N<1>的完整trace"
    product, project, build = merge_scope_from_question(
        q, config=config, engine=None
    )
    assert product == "ipad"
    assert project == "logan"
    assert build == "p1"


def test_alias_inference_without_catalog(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    product, project, build = infer_scope_from_aliases(
        "Scarif p0 flash erase", config
    )
    assert product == "ipad"
    assert project == "logan"
    assert build == "p0"


def test_explicit_api_scope_wins(repo_root: Path) -> None:
    config = load_config(repo_root=repo_root)
    product, project, build = merge_scope_from_question(
        "logan p1 anything",
        config=config,
        engine=None,
        product="iphone",
        project="other",
        build="dvt",
    )
    assert product == "iphone"
    assert project == "other"
    assert build == "dvt"
