"""Tests for rule-based scope extraction."""

from __future__ import annotations

import pytest

from ee_wiki.retrieval.scope_catalog import ScopeCatalog
from ee_wiki.retrieval.scope_extract import extract_scope_rules


@pytest.fixture
def catalog(data_layout) -> ScopeCatalog:
    return ScopeCatalog(
        products={"logan": frozenset({"p1", "p2"})},
        enterprise_segment=data_layout.enterprise_project,
        project_shared_segment=data_layout.project_shared_build,
    )


def test_logan_p1_build_scope(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("Logan p1 lcd的pin有哪些", catalog)
    assert result is not None
    assert result.product == "logan"
    assert result.revision == "p1"
    assert result.layer == "build"
    assert "lcd" in result.stripped_query.lower()
    assert "logan" not in result.stripped_query.lower()
    assert "p1" not in result.stripped_query.lower()


def test_logan_slash_p1(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("logan/p1 RMII pins", catalog)
    assert result is not None
    assert result.product == "logan"
    assert result.revision == "p1"
    assert result.layer == "build"


def test_logan_common_project_layer(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("logan common 架构说明", catalog)
    assert result is not None
    assert result.product == "logan"
    assert result.revision is None
    assert result.layer == "project_common"


def test_global_enterprise_layer(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("global CH340 pinout", catalog)
    assert result is not None
    assert result.product is None
    assert result.layer == "enterprise"


def test_standalone_revision_not_matched(catalog: ScopeCatalog) -> None:
    assert extract_scope_rules("p1 lcd pins", catalog) is None


def test_product_only_inherit(catalog: ScopeCatalog) -> None:
    result = extract_scope_rules("logan LCD wiring", catalog)
    assert result is not None
    assert result.product == "logan"
    assert result.revision is None
    assert result.layer == "inherit"
