"""Tests for explicit API/MCP product/project/build canonicalization."""

from __future__ import annotations

import pytest

from ee_wiki.common.errors import ScopeValidationError
from ee_wiki.common.project_aliases import (
    canonicalize_scope_filters,
    normalize_project_aliases,
)


def test_explicit_h340_maps_to_logan_project() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    product, project, build = canonicalize_scope_filters(
        "iPhone", "H340", "P1", aliases=aliases
    )
    assert product == "iphone"
    assert project == "logan"
    assert build == "p1"


def test_alias_applies_to_product_axis() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    product, project, build = canonicalize_scope_filters(
        "H340", None, None, aliases=aliases
    )
    assert product == "logan"
    assert project is None
    assert build is None


def test_none_filters_stay_none() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    product, project, build = canonicalize_scope_filters(
        None, None, None, aliases=aliases
    )
    assert product is None
    assert project is None
    assert build is None


def test_require_product_rejects_partial_scope() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    with pytest.raises(ScopeValidationError, match="product is required"):
        canonicalize_scope_filters(
            None, "logan", "p1", aliases=aliases, require_product=True
        )


def test_qualified_alias_fills_product() -> None:
    aliases = normalize_project_aliases({"H340": "iphone/logan"})
    product, project, build = canonicalize_scope_filters(
        None, "H340", "P1", aliases=aliases, require_product=True
    )
    assert product == "iphone"
    assert project == "logan"
    assert build == "p1"
