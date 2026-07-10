"""Tests for mapping inferred scope to retrieval targets."""

from __future__ import annotations

import pytest

from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_extract import InferredScope
from ee_wiki.retrieval.scope_resolve import resolve_retrieval_targets


@pytest.fixture
def catalog(data_layout) -> ScopeCatalog:
    return ScopeCatalog(
        products={"logan": frozenset({"p1", "p2"})},
        enterprise_segment=data_layout.enterprise_project,
        project_shared_segment=data_layout.project_shared_build,
    )


def test_build_scope_expands_with_inheritance(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(product="logan", revision="p1", layer="build")
    project, build, ranks = resolve_retrieval_targets(inferred, catalog, data_layout)
    assert project == "logan"
    assert build == "p1"
    assert ("logan", "p1") in ranks
    assert ("logan", "common") in ranks
    assert ("global", "global") in ranks
    assert ranks[("logan", "p1")] < ranks[("logan", "common")]


def test_project_common_scope(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(product="logan", layer="project_common")
    project, build, ranks = resolve_retrieval_targets(inferred, catalog, data_layout)
    assert project == "logan"
    assert build == "common"
    assert set(ranks) == {("logan", "common"), ("global", "global")}


def test_enterprise_scope(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(layer="enterprise")
    project, build, ranks = resolve_retrieval_targets(inferred, catalog, data_layout)
    assert project == "global"
    assert build == "global"
    assert ranks == {("global", "global"): 0}


def test_inherit_product_includes_all_revisions(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(product="logan", layer="inherit")
    project, build, ranks = resolve_retrieval_targets(inferred, catalog, data_layout)
    assert project == "logan"
    assert build is None
    assert ("logan", "p1") in ranks
    assert ("logan", "p2") in ranks
    assert ("logan", "common") in ranks
    assert ("global", "global") in ranks
    assert ranks[("logan", "p1")] == ranks[("logan", "p2")]
    assert ranks[("logan", "p1")] < ranks[("logan", "common")]
    assert ranks[("logan", "common")] < ranks[("global", "global")]
