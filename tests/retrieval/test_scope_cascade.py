"""Tests for scope cascade retrieval helpers."""

from __future__ import annotations

from ee_wiki.retrieval.hybrid.engine import HybridChunk
from ee_wiki.retrieval.scope_cascade import (
    SCOPE_TIER_BUILD,
    SCOPE_TIER_GLOBAL,
    SCOPE_TIER_PRODUCT_COMMON,
    SCOPE_TIER_PROJECT_COMMON,
    ScopeQuotas,
    assemble_mixed_quota,
    build_cascade_phases_from_ranks,
    effective_primary_quota,
    scope_tier,
    should_run_scope_cascade,
)


def _chunk(chunk_id: str, product: str, project: str, build: str) -> HybridChunk:
    return HybridChunk(
        chunk_id=chunk_id,
        content=f"content for {chunk_id}",
        metadata={
            "product": product,
            "project": project,
            "build": build,
            "document_type": "engineering_note",
        },
        citation={
            "source_file": f"data/raw/{product}/{project}/{build}/note/{chunk_id}.md"
        },
    )


def test_scope_tier_derivation(data_layout) -> None:
    assert scope_tier("iphone", "logan", "p1", data_layout) == SCOPE_TIER_BUILD
    assert (
        scope_tier("iphone", "logan", "common", data_layout)
        == SCOPE_TIER_PROJECT_COMMON
    )
    assert (
        scope_tier("iphone", "common", "common", data_layout)
        == SCOPE_TIER_PRODUCT_COMMON
    )
    assert scope_tier("global", "global", "global", data_layout) == SCOPE_TIER_GLOBAL


def test_build_cascade_phases_from_ranks_groups_inherit_builds(data_layout) -> None:
    scope_ranks = {
        ("iphone", "logan", "p1"): 0,
        ("iphone", "logan", "p2"): 0,
        ("iphone", "logan", "common"): 1,
        ("iphone", "common", "common"): 2,
        ("global", "global", "global"): 3,
    }
    phases = build_cascade_phases_from_ranks(scope_ranks, data_layout)
    assert len(phases) == 4
    assert phases[0].tier == SCOPE_TIER_BUILD
    assert phases[0].scope_triples == frozenset(
        {("iphone", "logan", "p1"), ("iphone", "logan", "p2")}
    )
    assert phases[1].tier == SCOPE_TIER_PROJECT_COMMON
    assert phases[2].tier == SCOPE_TIER_PRODUCT_COMMON
    assert phases[3].tier == SCOPE_TIER_GLOBAL


def test_effective_primary_quota_expands_for_common_primary() -> None:
    quotas = ScopeQuotas(build=6, common=2, global_=2)
    assert effective_primary_quota(
        SCOPE_TIER_PROJECT_COMMON,
        primary_tier=SCOPE_TIER_PROJECT_COMMON,
        final_k=8,
        quotas=quotas,
    ) == 4


def test_assemble_mixed_quota_build_primary_with_supplement() -> None:
    reranked = {
        SCOPE_TIER_BUILD: [
            (0.9, _chunk("b1", "iphone", "logan", "p1")),
            (0.8, _chunk("b2", "iphone", "logan", "p1")),
        ],
        SCOPE_TIER_PROJECT_COMMON: [
            (0.7, _chunk("c1", "iphone", "logan", "common"))
        ],
        SCOPE_TIER_GLOBAL: [(0.95, _chunk("g1", "global", "global", "global"))],
    }
    hits = assemble_mixed_quota(
        reranked,
        primary_tier=SCOPE_TIER_BUILD,
        final_k=4,
        quotas=ScopeQuotas(build=6, common=2, global_=2),
    )
    ids = [chunk.chunk_id for chunk in hits]
    assert ids[0] in {"b1", "b2"}
    assert "g1" not in ids[:2]
    assert len(hits) == 4
    assert hits[-1].chunk_id == "g1"


def test_should_run_scope_cascade_requires_inheritance_and_scope() -> None:
    assert should_run_scope_cascade(
        scope_inheritance=True,
        scope_cascade=True,
        target_product="iphone",
        scope_ranks={("iphone", "logan", "p1"): 0},
    )
    assert not should_run_scope_cascade(
        scope_inheritance=False,
        scope_cascade=True,
        target_product="iphone",
        scope_ranks={("iphone", "logan", "p1"): 0},
    )
    assert not should_run_scope_cascade(
        scope_inheritance=True,
        scope_cascade=False,
        target_product="iphone",
        scope_ranks={("iphone", "logan", "p1"): 0},
    )
