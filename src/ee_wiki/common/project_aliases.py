"""Canonicalize project names across 甲方 / 乙方 (and other) aliases."""

from __future__ import annotations

import re
from collections.abc import Mapping

from ee_wiki.common.errors import ScopeValidationError


def normalize_project_aliases(raw: dict[str, str]) -> dict[str, str]:
    """Normalize alias map to ``lowercase_alias → lowercase_canonical``.

    Canonical values may be a bare project slug (``logan``) or a product-qualified
    target (``iphone/logan``).

    Args:
        raw: Config mapping (e.g. ``H340: logan`` or ``H340: iphone/logan``).

    Returns:
        Casefolded alias → canonical target map.
    """
    out: dict[str, str] = {}
    for alias, canonical in raw.items():
        key = str(alias).strip().casefold()
        value = str(canonical).strip().casefold()
        if key and value:
            out[key] = value
    return out


def split_qualified_target(canonical: str) -> tuple[str | None, str]:
    """Split a canonical alias target into ``(product, project)``.

    Args:
        canonical: Bare slug (``logan``) or qualified ``product/project``.

    Returns:
        ``(product, project)`` when qualified; ``(None, slug)`` when bare.
    """
    text = canonical.strip().casefold()
    if not text:
        return None, ""
    if "/" in text:
        left, _, right = text.partition("/")
        if left and right and "/" not in right:
            return left, right
    return None, text


def resolve_alias_target(
    token: str | None,
    aliases: Mapping[str, str],
) -> tuple[str | None, str | None]:
    """Resolve a token through aliases to an optional product and project slug.

    Args:
        token: User, Radar, or API scope token.
        aliases: Normalized alias map.

    Returns:
        ``(product_hint, project_slug)``. Bare aliases yield
        ``(None, slug)``; qualified aliases yield ``(product, project)``.
        Empty tokens yield ``(None, None)``.
    """
    if token is None:
        return None, None
    normalized = token.strip().casefold()
    if not normalized:
        return None, None
    mapped = dict(aliases).get(normalized, normalized)
    product, project = split_qualified_target(mapped)
    if not project:
        return None, None
    return product, project


def canonicalize_project(
    token: str | None,
    aliases: dict[str, str],
) -> str | None:
    """Map a project token through aliases to the canonical project slug.

    Qualified alias targets (``iphone/logan``) return only the project segment
    (``logan``). Use :func:`resolve_alias_target` when the product hint is needed.

    Args:
        token: User, Radar, or catalog token.
        aliases: Normalized alias map from :func:`normalize_project_aliases`.

    Returns:
        Canonical lowercase project slug, or ``None`` when ``token`` is empty.
    """
    _product, project = resolve_alias_target(token, aliases)
    return project


def canonicalize_scope_filters(
    product: str | None,
    project: str | None,
    build: str | None,
    *,
    aliases: Mapping[str, str],
    require_product: bool = False,
) -> tuple[str | None, str | None, str | None]:
    """Normalize explicit API/MCP ``product`` / ``project`` / ``build`` filters.

    Applies ``project_aliases`` (e.g. ``H340`` → ``logan`` or
    ``H340`` → ``iphone/logan``) to the product and project axes and lowercases
    ``build`` (e.g. ``P1`` → ``p1``) so callers using 甲方代号 or mixed case
    match indexed ``data/raw/{product}/{project}/{build}/`` metadata.

    When an alias resolves to a product-qualified target on the project axis,
    the product hint fills ``product`` if the caller left it unset.

    Args:
        product: Optional product filter from REST/MCP/chat.
        project: Optional project filter.
        build: Optional build filter.
        aliases: Normalized alias map from config.
        require_product: When true, reject ``project``/``build`` without
            ``product`` (HTTP/MCP entrypoints). Fully unscoped (all ``None``)
            remains allowed.

    Returns:
        ``(canonical_product, canonical_project, canonical_build)``;
        ``None`` inputs stay ``None`` unless filled by a qualified alias.

    Raises:
        ScopeValidationError: When ``require_product`` is true and the filters
            are partially scoped without ``product``.
    """
    alias_map = dict(aliases)

    resolved_product: str | None = None
    if product:
        hint_product, slug = resolve_alias_target(product, alias_map)
        # Bare alias on the product axis keeps historical behavior (slug → product).
        # Qualified alias contributes the product segment only.
        resolved_product = hint_product if hint_product is not None else slug

    resolved_project: str | None = None
    project_product_hint: str | None = None
    if project:
        hint_product, slug = resolve_alias_target(project, alias_map)
        resolved_project = slug
        project_product_hint = hint_product

    if resolved_product is None and project_product_hint is not None:
        resolved_product = project_product_hint

    def _lower(value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        return str(value).strip().lower()

    resolved_build = _lower(build)

    if require_product and resolved_product is None and (
        resolved_project is not None or resolved_build is not None
    ):
        raise ScopeValidationError(
            "product is required when project or build is set; "
            "omit product, project, and build for unscoped search"
        )

    return resolved_product, resolved_project, resolved_build


def match_project_in_text(
    text: str,
    aliases: dict[str, str],
    *,
    known_projects: frozenset[str] | None = None,
) -> str | None:
    """Find a project alias or canonical slug mentioned in ``text``.

    Longer tokens win. Matched aliases resolve to the canonical project slug
    (qualified targets contribute the project segment only).

    Args:
        text: Free text (question, Radar component name, …).
        aliases: Normalized alias → canonical map.
        known_projects: Optional extra canonical slugs to match (e.g. from index).

    Returns:
        Canonical project slug when a token matches; otherwise ``None``.
    """
    candidates: set[str] = set(aliases.keys())
    for value in aliases.values():
        _product, project = split_qualified_target(value)
        if project:
            candidates.add(project)
    if known_projects:
        candidates |= {p.casefold() for p in known_projects if p}
    if not candidates or not text.strip():
        return None

    for token in sorted(candidates, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
        if pattern.search(text):
            return canonicalize_project(token, aliases)
    return None


def match_scope_in_text(
    text: str,
    aliases: dict[str, str],
    *,
    known_projects: frozenset[str] | None = None,
) -> tuple[str | None, str | None]:
    """Find a product-qualified project mention in ``text``.

    Args:
        text: Free text (question, Radar component name, …).
        aliases: Normalized alias map.
        known_projects: Optional extra canonical project slugs.

    Returns:
        ``(product_hint, project_slug)`` when a token matches; else
        ``(None, None)``.
    """
    project = match_project_in_text(
        text, aliases, known_projects=known_projects
    )
    if project is None:
        return None, None
    # Prefer the first alias key/value that resolves to this project.
    for alias, canonical in aliases.items():
        hint_product, slug = split_qualified_target(canonical)
        if slug == project and (
            re.search(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE)
            or re.search(rf"\b{re.escape(slug)}\b", text, re.IGNORECASE)
        ):
            return hint_product, project
    return None, project
