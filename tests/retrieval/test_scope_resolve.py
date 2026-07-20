"""Tests for mapping inferred scope to retrieval targets."""

from __future__ import annotations

import pytest

from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_extract import InferredScope
from ee_wiki.retrieval.scope_resolve import resolve_retrieval_targets


@pytest.fixture
def catalog(data_layout) -> ScopeCatalog:
    return ScopeCatalog(
        products={"iphone": {"logan": frozenset({"p1", "p2"})}},
        enterprise_segment=data_layout.enterprise_project,
        project_shared_segment=data_layout.project_shared_build,
    )


def test_build_scope_expands_with_inheritance(
    catalog: ScopeCatalog, data_layout
) -> None:
    inferred = InferredScope(
        product="iphone", project="logan", revision="p1", layer="build"
    )
    product, project, build, ranks = resolve_retrieval_targets(
        inferred, catalog, data_layout
    )
    assert product == "iphone"
    assert project == "logan"
    assert build == "p1"
    assert ("iphone", "logan", "p1") in ranks
    assert ("iphone", "logan", "common") in ranks
    assert ("iphone", "common", "common") in ranks
    assert ("global", "global", "global") in ranks
    assert ranks[("iphone", "logan", "p1")] < ranks[("iphone", "logan", "common")]
    assert ranks[("iphone", "logan", "common")] < ranks[("iphone", "common", "common")]


def test_project_common_scope(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(product="iphone", project="logan", layer="project_common")
    product, project, build, ranks = resolve_retrieval_targets(
        inferred, catalog, data_layout
    )
    assert product == "iphone"
    assert project == "logan"
    assert build == "common"
    assert set(ranks) == {
        ("iphone", "logan", "common"),
        ("iphone", "common", "common"),
        ("global", "global", "global"),
    }


def test_product_common_scope(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(product="iphone", layer="product_common")
    product, project, build, ranks = resolve_retrieval_targets(
        inferred, catalog, data_layout
    )
    assert product == "iphone"
    assert project == "common"
    assert build == "common"
    assert set(ranks) == {
        ("iphone", "common", "common"),
        ("global", "global", "global"),
    }


def test_enterprise_scope(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(layer="enterprise")
    product, project, build, ranks = resolve_retrieval_targets(
        inferred, catalog, data_layout
    )
    assert product == "global"
    assert project == "global"
    assert build == "global"
    assert ranks == {("global", "global", "global"): 0}


def test_inherit_product_includes_all_builds(catalog: ScopeCatalog, data_layout) -> None:
    inferred = InferredScope(product="iphone", layer="inherit")
    product, project, build, ranks = resolve_retrieval_targets(
        inferred, catalog, data_layout
    )
    assert product == "iphone"
    assert project is None
    assert build is None
    assert ("iphone", "logan", "p1") in ranks
    assert ("iphone", "logan", "p2") in ranks
    assert ("iphone", "logan", "common") in ranks
    assert ("iphone", "common", "common") in ranks
    assert ("global", "global", "global") in ranks
    assert ranks[("iphone", "logan", "p1")] == ranks[("iphone", "logan", "p2")]
    assert ranks[("iphone", "logan", "p1")] < ranks[("iphone", "logan", "common")]
    assert (
        ranks[("iphone", "logan", "common")] < ranks[("iphone", "common", "common")]
    )
    assert (
        ranks[("iphone", "common", "common")] < ranks[("global", "global", "global")]
    )


def test_ambiguous_build_never_leaks_other_products(data_layout) -> None:
    catalog = ScopeCatalog(
        products={
            "iphone": {
                "logan": frozenset({"p1"}),
                "macon": frozenset({"p1"}),
            },
            "ipad": {"demo": frozenset({"p1"})},
        },
        enterprise_segment=data_layout.enterprise_project,
        project_shared_segment=data_layout.project_shared_build,
    )
    inferred = InferredScope(product="iphone", revision="p1", layer="build")
    product, project, build, ranks = resolve_retrieval_targets(
        inferred, catalog, data_layout
    )
    assert product == "iphone"
    assert project is None
    assert build == "p1"
    assert ("iphone", "logan", "p1") in ranks
    assert ("iphone", "macon", "p1") in ranks
    assert all(triple[0] in {"iphone", "global"} for triple in ranks)
