"""Tests for rule-based scope extraction."""

from __future__ import annotations

import pytest

from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_extract import extract_scope_rules


@pytest.fixture
def catalog(data_layout) -> ScopeCatalog:
    return ScopeCatalog(
        products={"iphone": {"logan": frozenset({"p1", "p2"})}},
        enterprise_segment=data_layout.enterprise_project,
        project_shared_segment=data_layout.project_shared_build,
    )


def test_product_project_build_scope(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("iPhone Logan p1 lcd的pin有哪些", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.project == "logan"
    assert result.revision == "p1"
    assert result.layer == "build"
    assert "lcd" in result.stripped_query.lower()
    assert "logan" not in result.stripped_query.lower()
    assert "p1" not in result.stripped_query.lower()


def test_product_slash_project_slash_build(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("iphone/logan/p1 RMII pins", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.project == "logan"
    assert result.revision == "p1"
    assert result.layer == "build"


def test_project_common_layer(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("iphone logan common 架构说明", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.project == "logan"
    assert result.revision is None
    assert result.layer == "project_common"


def test_product_common_layer(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("iphone common 平台架构", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.project is None
    assert result.layer == "product_common"


def test_global_enterprise_layer(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("global CH340 pinout", catalog)
    assert result is not None
    assert result.product is None
    assert result.layer == "enterprise"


def test_standalone_revision_not_matched(catalog: ScopeCatalog) -> None:
    assert extract_scope_rules("p1 lcd pins", catalog) is None


def test_product_only_inherit(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("iphone LCD wiring", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.revision is None
    assert result.layer == "inherit"


def test_product_build_resolves_unique_project(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("iphone p1 lcd pin", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.project == "logan"
    assert result.revision == "p1"
    assert result.layer == "build"


def test_product_build_ambiguous_project_left_unset(data_layout) -> None:
    catalog = ScopeCatalog(
        products={
            "iphone": {
                "logan": frozenset({"p1"}),
                "macon": frozenset({"p1"}),
            }
        },
        enterprise_segment=data_layout.enterprise_project,
        project_shared_segment=data_layout.project_shared_build,
    )
    result = extract_scope_rules("iphone p1 lcd pin", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.project is None
    assert result.revision == "p1"
    assert result.layer == "build"


def test_customer_alias_resolves_to_canonical(data_layout) -> None:
    catalog = ScopeCatalog(
        products={"iphone": {"logan": frozenset({"p1", "p2"})}},
        enterprise_segment=data_layout.enterprise_project,
        project_shared_segment=data_layout.project_shared_build,
        project_aliases={"h340": "iphone"},
    )
    result = extract_scope_rules("H340 logan p1 lcd pin", catalog)
    assert result is not None
    assert result.product == "iphone"
    assert result.project == "logan"
    assert result.revision == "p1"
    assert result.layer == "build"
    assert "h340" not in result.stripped_query.lower()
