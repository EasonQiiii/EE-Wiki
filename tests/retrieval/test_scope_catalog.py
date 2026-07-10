"""Tests for scope catalog built from index metadata."""

from __future__ import annotations

from ee_wiki.retrieval.scope_catalog import ScopeCatalog


def test_global_excluded_from_products(data_layout) -> None:
    catalog = ScopeCatalog.from_metadata_pairs(
        [
            ("global", "global"),
            ("logan", "p1"),
            ("logan", "p2"),
            ("logan", "common"),
        ],
        data_layout,
    )
    assert "global" not in catalog.products
    assert catalog.products["logan"] == frozenset({"p1", "p2"})


def test_common_excluded_from_revisions(data_layout) -> None:
    catalog = ScopeCatalog.from_metadata_pairs(
        [("logan", "common"), ("logan", "p1")],
        data_layout,
    )
    assert "common" not in catalog.products["logan"]


def test_format_known_products(data_layout) -> None:
    catalog = ScopeCatalog.from_metadata_pairs(
        [("logan", "p2"), ("logan", "p1")],
        data_layout,
    )
    rendered = catalog.format_known_products()
    assert "logan: p1, p2" in rendered
