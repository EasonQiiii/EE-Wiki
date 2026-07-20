"""Tests for scope catalog built from index metadata."""

from __future__ import annotations

from ee_wiki.retrieval.scope_catalog import ScopeCatalog


def test_global_excluded_from_products(data_layout) -> None:
    catalog = ScopeCatalog.from_metadata_triples(
        [
            ("global", "global", "global"),
            ("iphone", "logan", "p1"),
            ("iphone", "logan", "p2"),
            ("iphone", "logan", "common"),
        ],
        data_layout,
    )
    assert "global" not in catalog.products
    assert catalog.products["iphone"]["logan"] == frozenset({"p1", "p2"})


def test_common_excluded_from_builds(data_layout) -> None:
    catalog = ScopeCatalog.from_metadata_triples(
        [("iphone", "logan", "common"), ("iphone", "logan", "p1")],
        data_layout,
    )
    assert "common" not in catalog.products["iphone"]["logan"]
    assert "common" not in catalog.products["iphone"]


def test_common_only_product_is_registered(data_layout) -> None:
    catalog = ScopeCatalog.from_metadata_triples(
        [("kingboo", "common", "common"), ("iphone", "logan", "p1")],
        data_layout,
    )
    assert "kingboo" in catalog.products
    assert catalog.products["kingboo"] == {}
    assert catalog.is_valid_product("kingboo")
    rendered = catalog.format_known_products()
    assert "kingboo" in rendered
    assert "common only" in rendered


def test_format_known_products(data_layout) -> None:
    catalog = ScopeCatalog.from_metadata_triples(
        [("iphone", "logan", "p2"), ("iphone", "logan", "p1")],
        data_layout,
    )
    rendered = catalog.format_known_products()
    assert "iphone" in rendered
    assert "logan (p1, p2)" in rendered


def test_same_slugs_isolated_per_product(data_layout) -> None:
    """Identical project/build slugs under two products stay separate."""
    catalog = ScopeCatalog.from_metadata_triples(
        [("iphone", "demo", "p1"), ("ipad", "demo", "p1")],
        data_layout,
    )
    assert catalog.builds_for("iphone", "demo") == frozenset({"p1"})
    assert catalog.builds_for("ipad", "demo") == frozenset({"p1"})
    assert catalog.projects_with_build("iphone", "p1") == ["demo"]
    assert catalog.is_valid_build("iphone", "demo", "p1")
    assert not catalog.is_valid_build("iphone", "other", "p1")
