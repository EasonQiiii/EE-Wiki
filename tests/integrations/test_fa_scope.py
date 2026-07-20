"""Tests for Radar → EE-Wiki scope mapping via project aliases."""

from __future__ import annotations

from ee_wiki.common.project_aliases import normalize_project_aliases
from ee_wiki.integrations.scope import (
    normalize_build,
    resolve_scope_from_component,
)
from ee_wiki.protocols.radar import RadarComponentRef, RadarScopeHint


def test_normalize_build_lowercases() -> None:
    assert normalize_build("P1") == "p1"
    assert normalize_build("  EVT ") == "evt"


def test_user_override_canonicalizes_alias() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    component = RadarComponentRef(id=1, name="Other", version="P2")
    result = resolve_scope_from_component(
        component,
        project_aliases=aliases,
        user_product="iphone",
        user_project="H340",
        user_build="P1",
    )
    assert result.product == "iphone"
    assert result.project == "logan"
    assert result.build == "p1"
    assert result.source == "user_override"


def test_customer_code_in_component_name() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    component = RadarComponentRef(id=1, name="H340 HW", version="P1")
    result = resolve_scope_from_component(
        component,
        project_aliases=aliases,
    )
    assert result.project == "logan"
    assert result.build == "p1"
    assert result.source == "component_alias"
    assert result.confidence == "high"


def test_vendor_slug_in_component_name() -> None:
    aliases = normalize_project_aliases({"H340": "logan"})
    component = RadarComponentRef(id=1, name="Logan HW", version="P1")
    result = resolve_scope_from_component(
        component,
        project_aliases=aliases,
    )
    assert result.project == "logan"
    assert result.build == "p1"


def test_found_in_build_fallback() -> None:
    result = resolve_scope_from_component(
        None,
        hint=RadarScopeHint(found_in_builds=("P3",)),
    )
    assert result.project is None
    assert result.build == "p3"
    assert result.source == "found_in_build"
    assert result.confidence == "low"
